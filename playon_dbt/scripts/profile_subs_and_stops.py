"""Profiling pass 3 — three specific questions.

1. Do users hold *concurrent* subscriptions, or is one-per-user-at-a-time with repeats over
   time? (Determines the grain of any subscription dimension.)
2. Does a `stop` event fire at natural end-of-video, or only on user action? (Determines
   whether "watched to the end" is observable, and whether stop position is trustworthy.)
3. Are the timestamp columns in the OTHER three files also multi-format? Pass 1 only checked
   playback_events.event_ts.

Run: .venv/Scripts/python.exe scripts/profile_subs_and_stops.py
Prerequisite: the raw extracts are landed -- ./.venv/Scripts/python.exe scripts/load_raw.py
"""

import pathlib
import sys
import duckdb

DB = pathlib.Path(__file__).resolve().parent.parent / "playon.duckdb"

# --------------------------------------------------------------------------------- preflight
# This script reads tables it does not build. Without the check below, an unbuilt prerequisite
# surfaces as a bare CatalogException partway through the run -- after several blocks have
# already printed results -- which reads like a broken query rather than a missing dependency.
NEEDS = (
    "raw.playback_events",
    "raw.subscriptions",
    "raw.asset_catalog",
    "raw.users",
)
BUILD_WITH = "./.venv/Scripts/python.exe scripts/load_raw.py"


def preflight():
    """Return a read-only connection, or exit with the command that fixes the problem."""
    if not DB.exists():
        sys.exit(f"no database at {DB}\n  build it: {BUILD_WITH}")
    try:
        con = duckdb.connect(str(DB), read_only=True)
    except duckdb.IOException as exc:
        # Not corruption: the DuckDB UI holds an exclusive lock while it runs (CLAUDE.md 6.5).
        sys.exit(
            f"cannot open {DB.name} -- {exc}\n"
            "  if scripts/duckdb_ui.py is running, stop it and retry"
        )
    have = {
        f"{s}.{t}"
        for s, t in con.execute(
            "SELECT table_schema, table_name FROM information_schema.tables"
        ).fetchall()
    }
    missing = [t for t in NEEDS if t not in have]
    if missing:
        con.close()
        sys.exit(f"missing {', '.join(missing)}\n  build it: {BUILD_WITH}")
    return con


con = preflight()


def show(title, sql, params=None):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)
    rel = con.execute(sql, params or [])
    cols = [d[0] for d in rel.description]
    rows = rel.fetchall()
    if not rows:
        print("(no rows)")
        return
    widths = [
        max(len(str(c)), max(len(str(r[i])) for r in rows)) for i, c in enumerate(cols)
    ]
    print("  ".join(str(c).ljust(w) for c, w in zip(cols, widths)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(str(v).ljust(w) for v, w in zip(r, widths)))


# ============================================================ 3. timestamp formats elsewhere
show(
    "TIMESTAMP FORMATS in the other three files",
    """
    SELECT 'subscriptions.event_effective_ts' AS col,
           count(*) FILTER (WHERE regexp_matches(event_effective_ts, '^[0-9]+$')) AS epoch,
           count(*) FILTER (WHERE event_effective_ts LIKE '%T%Z')                 AS iso_z,
           count(*) FILTER (WHERE event_effective_ts LIKE '% %')                  AS iso_space,
           count(*) FILTER (WHERE event_effective_ts IS NULL
                               OR event_effective_ts = '')                        AS missing
      FROM raw.subscriptions
    UNION ALL
    SELECT 'users.signup_ts',
           count(*) FILTER (WHERE regexp_matches(signup_ts, '^[0-9]+$')),
           count(*) FILTER (WHERE signup_ts LIKE '%T%Z'),
           count(*) FILTER (WHERE signup_ts LIKE '% %'),
           count(*) FILTER (WHERE signup_ts IS NULL OR signup_ts = '')
      FROM raw.users
    UNION ALL
    SELECT 'asset_catalog.scheduled_start_ts',
           count(*) FILTER (WHERE regexp_matches(scheduled_start_ts, '^[0-9]+$')),
           count(*) FILTER (WHERE scheduled_start_ts LIKE '%T%Z'),
           count(*) FILTER (WHERE scheduled_start_ts LIKE '% %'),
           count(*) FILTER (WHERE scheduled_start_ts IS NULL OR scheduled_start_ts = '')
      FROM raw.asset_catalog
    """,
)

# ============================================================ 1. subscription concurrency
show(
    "SUBSCRIPTIONS — how many per user, and what does a multi-sub user look like?",
    """
    SELECT n_subs AS subscriptions_held, count(*) AS users
      FROM (SELECT user_id, count(DISTINCT subscription_id) AS n_subs
              FROM raw.subscriptions GROUP BY 1)
     GROUP BY 1 ORDER BY 1
    """,
)

show(
    "SUBSCRIPTIONS — do one user's subscriptions OVERLAP in time (truly concurrent)?",
    """
    WITH span AS (
      SELECT user_id, subscription_id,
             min(TRY_CAST(event_effective_ts AS TIMESTAMP)) AS first_ts,
             max(TRY_CAST(event_effective_ts AS TIMESTAMP)) AS last_ts
        FROM raw.subscriptions GROUP BY 1,2)
    SELECT count(*) AS overlapping_pairs,
           count(DISTINCT a.user_id) AS users_with_overlap
      FROM span a JOIN span b
        ON a.user_id = b.user_id
       AND a.subscription_id < b.subscription_id
       AND a.first_ts <= b.last_ts
       AND b.first_ts <= a.last_ts
    """,
)

show(
    "SUBSCRIPTIONS — a worked example: every row for one 3-row subscription",
    """
    SELECT * FROM raw.subscriptions
     WHERE subscription_id = (
       SELECT subscription_id FROM raw.subscriptions
        GROUP BY 1 HAVING count(*) = 3 ORDER BY 1 LIMIT 1)
     ORDER BY event_effective_ts
    """,
)

show(
    "SUBSCRIPTIONS — a worked example: every row for one user holding several subscriptions",
    """
    SELECT * FROM raw.subscriptions
     WHERE user_id = (
       SELECT user_id FROM raw.subscriptions
        GROUP BY 1 HAVING count(DISTINCT subscription_id) >= 4
        ORDER BY count(*) DESC LIMIT 1)
     ORDER BY subscription_id, event_effective_ts
    """,
)

show(
    "SUBSCRIPTIONS — status sequence per subscription (the lifecycle shapes present)",
    """
    SELECT path, count(*) AS subscriptions
      FROM (SELECT subscription_id,
                   string_agg(status, ' -> ' ORDER BY event_effective_ts) AS path
              FROM raw.subscriptions GROUP BY 1)
     GROUP BY 1 ORDER BY 2 DESC
    """,
)

# ============================================================ 2. stop semantics
show(
    "STOP EVENTS — one per session, or several?",
    """
    SELECT n_stops, count(*) AS sessions
      FROM (SELECT session_id, count(*) FILTER (WHERE event_type = 'stop') AS n_stops
              FROM raw.playback_events GROUP BY 1)
     GROUP BY 1 ORDER BY 1
    """,
)

show(
    "STOP POSITION vs ASSET DURATION — does stop fire at the natural end of the video?",
    """
    WITH asset AS (
      SELECT DISTINCT ON (asset_id) asset_id,
             TRY_CAST(duration_seconds AS DOUBLE) AS dur
        FROM raw.asset_catalog),
    stops AS (
      SELECT p.session_id, a.dur,
             max(TRY_CAST(p.position_seconds AS DOUBLE))
               FILTER (WHERE p.event_type = 'stop') AS stop_pos
        FROM raw.playback_events p JOIN asset a USING (asset_id)
       WHERE a.dur > 0
       GROUP BY 1,2)
    SELECT CASE
             WHEN stop_pos / dur >= 0.98 THEN 'a. >=98% of asset (natural end)'
             WHEN stop_pos / dur >= 0.90 THEN 'b. 90-98%'
             WHEN stop_pos / dur >= 0.50 THEN 'c. 50-90%'
             WHEN stop_pos / dur >= 0.10 THEN 'd. 10-50%'
             ELSE                             'e. <10% (early abandon)'
           END AS stop_point, count(*) AS sessions,
           round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
      FROM stops WHERE stop_pos IS NOT NULL
     GROUP BY 1 ORDER BY 1
    """,
)

show(
    "STOP POSITION vs LAST HEARTBEAT — is stop just the final heartbeat position?",
    """
    WITH s AS (
      SELECT session_id,
             max(TRY_CAST(position_seconds AS DOUBLE))
               FILTER (WHERE event_type = 'stop')      AS stop_pos,
             max(TRY_CAST(position_seconds AS DOUBLE))
               FILTER (WHERE event_type = 'heartbeat') AS last_hb_pos
        FROM raw.playback_events GROUP BY 1)
    SELECT CASE WHEN stop_pos = last_hb_pos              THEN 'identical'
                WHEN stop_pos > last_hb_pos              THEN 'stop is later'
                WHEN stop_pos < last_hb_pos              THEN 'stop is EARLIER'
                ELSE 'null somewhere' END AS relation,
           count(*) AS sessions,
           round(avg(stop_pos - last_hb_pos), 1) AS avg_gap_seconds
      FROM s GROUP BY 1 ORDER BY 2 DESC
    """,
)

show(
    "STOP semantics by asset_type — LIVE vs VOD behave differently?",
    """
    WITH asset AS (
      SELECT DISTINCT ON (asset_id) asset_id, asset_type,
             TRY_CAST(duration_seconds AS DOUBLE) AS dur
        FROM raw.asset_catalog),
    stops AS (
      SELECT p.session_id, a.asset_type, a.dur,
             max(TRY_CAST(p.position_seconds AS DOUBLE))
               FILTER (WHERE p.event_type = 'stop') AS stop_pos
        FROM raw.playback_events p JOIN asset a USING (asset_id)
       WHERE a.dur > 0 GROUP BY 1,2,3)
    SELECT asset_type, count(*) AS sessions,
           round(avg(stop_pos / dur), 3) AS avg_completion_at_stop,
           round(quantile_cont(stop_pos / dur, 0.5), 3) AS median_completion_at_stop,
           count(*) FILTER (WHERE stop_pos / dur >= 0.98) AS reached_98pct
      FROM stops WHERE stop_pos IS NOT NULL
     GROUP BY 1 ORDER BY 1
    """,
)

con.close()
print("\n" + "=" * 78)
print("done")
