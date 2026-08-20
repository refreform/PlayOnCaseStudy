"""Profiling pass 2 — chase the specific defects pass 1 surfaced.

Pass 1 (profile_raw.py) found the shape. This pass answers "how bad, and what shape is the
damage" for each issue, plus gathers the distributions the engaged-view decision needs.

Note the FK counts here use anti-joins, not LEFT JOINs. Pass 1's orphan block used a LEFT JOIN
and reported 218,782 child rows against a 216,045-row table — it fanned out on the duplicated
asset_catalog.asset_id. That bug is kept in pass 1 deliberately as an artifact: it is the
cheapest possible demonstration of why the duplicate keys matter.

Run: .venv/Scripts/python.exe scripts/profile_raw_2.py
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


# ------------------------------------------------- FK orphans, done correctly
show(
    "FK ORPHANS (anti-join — no fan-out)",
    """
    SELECT 'events -> asset_catalog' AS fk,
           count(*) AS orphan_rows,
           count(DISTINCT asset_id) AS orphan_keys
      FROM raw.playback_events
     WHERE asset_id NOT IN (SELECT asset_id FROM raw.asset_catalog)
    UNION ALL
    SELECT 'events -> users (non-null only)', count(*), count(DISTINCT user_id)
      FROM raw.playback_events
     WHERE user_id IS NOT NULL
       AND user_id NOT IN (SELECT user_id FROM raw.users)
    UNION ALL
    SELECT 'subscriptions -> users', count(*), count(DISTINCT user_id)
      FROM raw.subscriptions
     WHERE user_id NOT IN (SELECT user_id FROM raw.users)
    """,
)

show(
    "FAN-OUT PROOF — joining events to the duplicated asset_catalog",
    """
    SELECT (SELECT count(*) FROM raw.playback_events) AS events_before,
           (SELECT count(*) FROM raw.playback_events p
              JOIN raw.asset_catalog a USING (asset_id)) AS events_after_inner_join,
           (SELECT count(*) FROM raw.playback_events p
              LEFT JOIN raw.asset_catalog a USING (asset_id)) AS events_after_left_join
    """,
)

# ------------------------------------------------- duplicate keys: what shape?
show(
    "DUPLICATE asset_id — are the duplicate rows identical or conflicting?",
    """
    SELECT asset_id, count(*) AS n_rows,
           count(DISTINCT title) AS n_titles,
           count(DISTINCT asset_type) AS n_types,
           count(DISTINCT sport) AS n_sports,
           count(DISTINCT duration_seconds) AS n_durations,
           count(DISTINCT (title, asset_type, sport, home_school, away_school,
                           scheduled_start_ts, duration_seconds)) AS n_distinct_full_rows
      FROM raw.asset_catalog
     GROUP BY 1 HAVING count(*) > 1
     ORDER BY 1
    """,
)

show(
    "DUPLICATE event_id — identical rows, or different events sharing an id?",
    """
    SELECT n_rows_per_id, count(*) AS n_event_ids,
           sum(CASE WHEN n_distinct_full = 1 THEN 1 ELSE 0 END) AS ids_with_identical_rows,
           sum(CASE WHEN n_distinct_full > 1 THEN 1 ELSE 0 END) AS ids_with_conflicting_rows
      FROM (
        SELECT event_id, count(*) AS n_rows_per_id,
               count(DISTINCT (session_id, user_id, asset_id, event_type, event_ts,
                               position_seconds, device_type, app_version,
                               bitrate_kbps)) AS n_distinct_full
          FROM raw.playback_events GROUP BY 1 HAVING count(*) > 1)
     GROUP BY 1 ORDER BY 1
    """,
)

# ------------------------------------------------- timestamp encoding correlates
show(
    "event_ts ENCODING vs app_version — is the format a client bug?",
    """
    SELECT app_version,
           count(*) FILTER (WHERE regexp_matches(event_ts, '^[0-9]+$')) AS epoch,
           count(*) FILTER (WHERE event_ts LIKE '%T%Z') AS iso_z,
           count(*) FILTER (WHERE event_ts LIKE '% %') AS iso_space
      FROM raw.playback_events GROUP BY 1 ORDER BY 1
    """,
)

show(
    "event_ts ENCODING vs device_type",
    """
    SELECT device_type,
           count(*) FILTER (WHERE regexp_matches(event_ts, '^[0-9]+$')) AS epoch,
           count(*) FILTER (WHERE event_ts LIKE '%T%Z') AS iso_z,
           count(*) FILTER (WHERE event_ts LIKE '% %') AS iso_space
      FROM raw.playback_events GROUP BY 1 ORDER BY 1
    """,
)

show(
    "DO THE THREE ENCODINGS COVER THE SAME PERIOD? (sanity on normalization)",
    """
    SELECT shape, count(*) AS rows,
           min(ts_utc) AS min_ts, max(ts_utc) AS max_ts
      FROM (
        SELECT CASE WHEN regexp_matches(event_ts, '^[0-9]+$') THEN 'epoch'
                    WHEN event_ts LIKE '%T%Z' THEN 'iso_z'
                    ELSE 'iso_space' END AS shape,
               CASE WHEN regexp_matches(event_ts, '^[0-9]+$')
                    THEN to_timestamp(TRY_CAST(event_ts AS BIGINT))
                    ELSE TRY_CAST(replace(replace(event_ts,'T',' '),'Z','') AS TIMESTAMP)
               END AS ts_utc
          FROM raw.playback_events)
     GROUP BY 1 ORDER BY 1
    """,
)

# ------------------------------------------------- null user_id shape
show(
    "NULL user_id — whole sessions, or scattered within sessions?",
    """
    SELECT CASE WHEN n_null = 0 THEN 'no nulls'
                WHEN n_null = n_events THEN 'entire session anonymous'
                ELSE 'MIXED within session' END AS pattern,
           count(*) AS sessions, sum(n_events) AS events
      FROM (SELECT session_id, count(*) AS n_events,
                   count(*) FILTER (WHERE user_id IS NULL) AS n_null
              FROM raw.playback_events GROUP BY 1)
     GROUP BY 1 ORDER BY 2 DESC
    """,
)

# ------------------------------------------------- duration / position sanity
show(
    "asset_catalog.duration_seconds — the bad rows",
    """
    SELECT asset_id, asset_type, sport, duration_seconds
      FROM raw.asset_catalog
     WHERE TRY_CAST(duration_seconds AS DOUBLE) <= 0
        OR duration_seconds IS NULL
     ORDER BY TRY_CAST(duration_seconds AS DOUBLE)
    """,
)

show(
    "POSITION vs DURATION — playhead beyond the end of the asset?",
    """
    SELECT count(*) AS events_checked,
           count(*) FILTER (WHERE pos > dur) AS pos_beyond_duration,
           count(*) FILTER (WHERE pos > dur * 1.05) AS pos_beyond_duration_5pct,
           round(max(pos / nullif(dur, 0)), 3) AS max_ratio
      FROM (
        SELECT TRY_CAST(p.position_seconds AS DOUBLE) AS pos,
               TRY_CAST(a.duration_seconds AS DOUBLE) AS dur
          FROM raw.playback_events p
          JOIN (SELECT DISTINCT ON (asset_id) asset_id, duration_seconds
                  FROM raw.asset_catalog) a USING (asset_id)
         WHERE TRY_CAST(a.duration_seconds AS DOUBLE) > 0)
    """,
)

# ------------------------------------------------- currency / mrr semantics
show(
    "CURRENCY — is mrr_amount summable across rows?",
    """
    SELECT currency, plan_type, count(*) AS rows,
           count(DISTINCT mrr_amount) AS distinct_amounts,
           min(mrr_amount) AS min_amt, max(mrr_amount) AS max_amt
      FROM raw.subscriptions GROUP BY 1,2 ORDER BY 1,2
    """,
)

# ------------------------------------------------- heartbeat cadence (engagement input)
show(
    "HEARTBEAT CADENCE — gap between consecutive heartbeats, by position_seconds",
    """
    WITH hb AS (
      SELECT session_id, TRY_CAST(position_seconds AS DOUBLE) AS pos,
             row_number() OVER (PARTITION BY session_id
                                ORDER BY TRY_CAST(position_seconds AS DOUBLE)) AS rn
        FROM raw.playback_events WHERE event_type = 'heartbeat')
    SELECT gap_seconds, count(*) AS occurrences
      FROM (SELECT pos - lag(pos) OVER (PARTITION BY session_id ORDER BY rn) AS gap_seconds
              FROM hb)
     WHERE gap_seconds IS NOT NULL
     GROUP BY 1 ORDER BY 2 DESC LIMIT 15
    """,
)

show(
    "SESSION WATCH SHAPE — heartbeats and max playhead per session",
    """
    SELECT quantile_cont(n_heartbeats, [0, .1, .25, .5, .75, .9, 1]) AS heartbeats_pctiles,
           quantile_cont(max_pos,      [0, .1, .25, .5, .75, .9, 1]) AS max_position_pctiles
      FROM (SELECT session_id,
                   count(*) FILTER (WHERE event_type = 'heartbeat') AS n_heartbeats,
                   max(TRY_CAST(position_seconds AS DOUBLE)) AS max_pos
              FROM raw.playback_events GROUP BY 1)
    """,
)

show(
    "COMPLETION RATIO — max playhead / asset duration, distribution",
    """
    SELECT round(ratio_bucket, 1) AS completion_bucket, count(*) AS sessions
      FROM (
        SELECT least(floor(max_pos / dur * 10) / 10.0, 1.0) AS ratio_bucket
          FROM (SELECT p.session_id,
                       max(TRY_CAST(p.position_seconds AS DOUBLE)) AS max_pos,
                       max(TRY_CAST(a.duration_seconds AS DOUBLE)) AS dur
                  FROM raw.playback_events p
                  JOIN (SELECT DISTINCT ON (asset_id) asset_id, duration_seconds
                          FROM raw.asset_catalog) a USING (asset_id)
                 GROUP BY 1)
         WHERE dur > 0)
     GROUP BY 1 ORDER BY 1
    """,
)

con.close()
print("\n" + "=" * 78)
print("done")
