"""Profiling pass 4 — return viewing, and the residual checks before staging.

The question: a session that stopped at 15% might be an abandon, or might be someone who came
back later and finished. Session-grain completion cannot tell those apart. Since engagement is
a *user*-level property, the unit that matters is (user, asset) across sessions, and then the
user across assets.

There is no seek event in this data, so a position jump is inherently ambiguous between "user
skipped ahead" and "heartbeat was dropped". That ambiguity is measured here, not resolved.

Run: .venv/Scripts/python.exe scripts/profile_return_viewing.py
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


# ================================================== do users return to the same asset?
show(
    "RETURN VIEWING — sessions per (user, asset)",
    """
    SELECT sessions_on_asset, count(*) AS user_asset_pairs
      FROM (SELECT user_id, asset_id, count(DISTINCT session_id) AS sessions_on_asset
              FROM raw.playback_events
             WHERE user_id IS NOT NULL
             GROUP BY 1,2)
     GROUP BY 1 ORDER BY 1
    """,
)

show(
    "RETURN VIEWING — how many users EVER rewatch any asset?",
    """
    SELECT count(DISTINCT user_id) AS users_with_playback,
           count(DISTINCT user_id) FILTER (WHERE has_repeat) AS users_who_rewatch
      FROM (SELECT user_id,
                   max(CASE WHEN n > 1 THEN true ELSE false END) AS has_repeat
              FROM (SELECT user_id, asset_id, count(DISTINCT session_id) AS n
                      FROM raw.playback_events WHERE user_id IS NOT NULL
                     GROUP BY 1,2)
             GROUP BY 1)
    """,
)

# ================================================== does rewatching change the completion picture?
show(
    "SESSION-GRAIN vs USER-ASSET-GRAIN completion — does aggregating change the story?",
    """
    WITH asset AS (
      SELECT DISTINCT ON (asset_id) asset_id,
             TRY_CAST(duration_seconds AS DOUBLE) AS dur
        FROM raw.asset_catalog),
    sess AS (
      SELECT p.user_id, p.asset_id, p.session_id, a.dur,
             max(TRY_CAST(p.position_seconds AS DOUBLE)) AS max_pos
        FROM raw.playback_events p JOIN asset a USING (asset_id)
       WHERE a.dur > 0 AND p.user_id IS NOT NULL
       GROUP BY 1,2,3,4)
    SELECT 'per session'    AS grain,
           count(*)         AS units,
           round(avg(max_pos / dur), 4) AS avg_completion,
           count(*) FILTER (WHERE max_pos / dur > 0.2) AS above_0_2,
           round(100.0 * count(*) FILTER (WHERE max_pos / dur > 0.2) / count(*), 1) AS pct_above_0_2
      FROM sess
    UNION ALL
    SELECT 'per (user, asset)', count(*), round(avg(best / dur), 4),
           count(*) FILTER (WHERE best / dur > 0.2),
           round(100.0 * count(*) FILTER (WHERE best / dur > 0.2) / count(*), 1)
      FROM (SELECT user_id, asset_id, max(dur) AS dur, max(max_pos) AS best
              FROM sess GROUP BY 1,2)
    """,
)

show(
    "REPEAT VIEWERS ONLY — does the second session resume, or restart?",
    """
    WITH sess AS (
      SELECT user_id, asset_id, session_id,
             min(TRY_CAST(position_seconds AS DOUBLE)) AS min_pos,
             max(TRY_CAST(position_seconds AS DOUBLE)) AS max_pos
        FROM raw.playback_events WHERE user_id IS NOT NULL
       GROUP BY 1,2,3),
    ranked AS (
      SELECT *, row_number() OVER (PARTITION BY user_id, asset_id ORDER BY min_pos) AS seq,
             count(*)   OVER (PARTITION BY user_id, asset_id) AS n_sessions
        FROM sess)
    SELECT CASE WHEN min_pos <= 60 THEN 'restarts near 0 (min_pos <= 60s)'
                ELSE 'starts later in the asset (resume-like)' END AS second_session_behaviour,
           count(*) AS sessions
      FROM ranked WHERE n_sessions > 1 AND seq > 1
     GROUP BY 1 ORDER BY 2 DESC
    """,
)

# ================================================== within-session position jumps
show(
    "WITHIN-SESSION JUMPS — heartbeat position gaps > 60s (dropped beat, or a seek?)",
    """
    WITH hb AS (
      SELECT session_id, TRY_CAST(position_seconds AS DOUBLE) AS pos
        FROM raw.playback_events WHERE event_type = 'heartbeat'),
    gaps AS (
      SELECT session_id, pos - lag(pos) OVER (PARTITION BY session_id ORDER BY pos) AS gap
        FROM hb)
    SELECT count(DISTINCT session_id) FILTER (WHERE gap > 60) AS sessions_with_a_jump,
           count(*) FILTER (WHERE gap > 60)                   AS jump_count,
           max(gap)                                           AS largest_jump_seconds
      FROM gaps
    """,
)

show(
    "PAUSE BEHAVIOUR — do sessions with a pause resume, and how far in?",
    """
    WITH asset AS (
      SELECT DISTINCT ON (asset_id) asset_id,
             TRY_CAST(duration_seconds AS DOUBLE) AS dur FROM raw.asset_catalog),
    s AS (
      SELECT p.session_id, a.dur,
             count(*) FILTER (WHERE event_type = 'pause') AS n_pause,
             max(TRY_CAST(position_seconds AS DOUBLE))
               FILTER (WHERE event_type = 'pause')        AS pause_pos,
             max(TRY_CAST(position_seconds AS DOUBLE))    AS max_pos
        FROM raw.playback_events p JOIN asset a USING (asset_id)
       WHERE a.dur > 0 GROUP BY 1,2)
    SELECT CASE WHEN n_pause = 0 THEN 'no pause' ELSE 'has pause' END AS pause_state,
           count(*) AS sessions,
           round(avg(max_pos / dur), 3) AS avg_completion,
           count(*) FILTER (WHERE max_pos > pause_pos) AS resumed_past_pause
      FROM s GROUP BY 1 ORDER BY 1
    """,
)

# ================================================== user-level engagement shape
show(
    "USER-LEVEL SHAPE — breadth and depth of viewing per user",
    """
    WITH u AS (
      SELECT user_id,
             count(DISTINCT session_id) AS sessions,
             count(DISTINCT asset_id)   AS assets,
             count(*) FILTER (WHERE event_type = 'heartbeat') AS heartbeats
        FROM raw.playback_events WHERE user_id IS NOT NULL GROUP BY 1)
    SELECT 'sessions per user'   AS metric,
           quantile_cont(sessions,   [0,.25,.5,.75,.9,1]) AS pctiles_0_25_50_75_90_100 FROM u
    UNION ALL SELECT 'assets per user',   quantile_cont(assets,   [0,.25,.5,.75,.9,1]) FROM u
    UNION ALL SELECT 'heartbeats (mins) per user', quantile_cont(heartbeats,[0,.25,.5,.75,.9,1]) FROM u
    """,
)

# ================================================== residual data checks before staging
show(
    "WHITESPACE — any leading/trailing spaces hiding in the categoricals?",
    """
    SELECT 'asset_catalog.sport' AS col,
           count(*) FILTER (WHERE sport <> trim(sport)) AS untrimmed FROM raw.asset_catalog
    UNION ALL SELECT 'asset_catalog.home_school',
           count(*) FILTER (WHERE home_school <> trim(home_school)) FROM raw.asset_catalog
    UNION ALL SELECT 'asset_catalog.title',
           count(*) FILTER (WHERE title <> trim(title)) FROM raw.asset_catalog
    UNION ALL SELECT 'users.home_state',
           count(*) FILTER (WHERE home_state <> trim(home_state)) FROM raw.users
    UNION ALL SELECT 'users.acquisition_channel',
           count(*) FILTER (WHERE acquisition_channel <> trim(acquisition_channel)) FROM raw.users
    UNION ALL SELECT 'playback_events.device_type',
           count(*) FILTER (WHERE device_type <> trim(device_type)) FROM raw.playback_events
    UNION ALL SELECT 'playback_events.event_type',
           count(*) FILTER (WHERE event_type <> trim(event_type)) FROM raw.playback_events
    UNION ALL SELECT 'subscriptions.status',
           count(*) FILTER (WHERE status <> trim(status)) FROM raw.subscriptions
    """,
)

show(
    "users.home_state — the actual bad values",
    """
    SELECT home_state, count(*) AS users FROM raw.users
     WHERE length(home_state) <> 2 OR home_state <> upper(home_state)
     GROUP BY 1 ORDER BY 2 DESC
    """,
)

show(
    "FULL-ROW DUPLICATES in the smaller tables",
    """
    SELECT 'users' AS tbl, count(*) - count(DISTINCT (user_id, signup_ts, home_state,
             acquisition_channel)) AS dupe_rows FROM raw.users
    UNION ALL
    SELECT 'subscriptions', count(*) - count(DISTINCT (subscription_id, user_id, plan_type,
             status, event_effective_ts, mrr_amount, currency)) FROM raw.subscriptions
    """,
)

con.close()
print("\n" + "=" * 78)
print("done")
