"""Profiling pass 6 — can heartbeat timing infer seeking, buffering, or real pausing?

The idea being tested: between two consecutive heartbeats we know both how much WALL TIME
passed and how far the PLAYHEAD moved. Comparing them discriminates cases the explicit event
types cannot:

    time +60s, position +60s   -> normal playback
    time +60s, position   +0s  -> stalled: buffering, or genuinely paused
    time +60s, position +300s  -> seek forward (playhead outran the clock)
    time +300s, position +300s -> dropped heartbeats (both outran together)

Earlier passes only ever compared positions, which cannot tell a dropped heartbeat from a
seek. This pass is the one that can.

Run: .venv/Scripts/python.exe scripts/profile_heartbeat_gaps.py
Prerequisite: the staging layer is built -- ./.venv/Scripts/dbt.exe build
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
    "main_staging.stg_playback_events",
)
BUILD_WITH = "./.venv/Scripts/dbt.exe build"


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


# ---------------------------------------------- the core test: time delta vs position delta
show(
    "HEARTBEAT-TO-HEARTBEAT — does the playhead track the clock?",
    """
    WITH hb AS (
      SELECT session_id, event_at_utc, position_seconds,
             lag(event_at_utc)     OVER (PARTITION BY session_id ORDER BY event_at_utc) AS prev_ts,
             lag(position_seconds) OVER (PARTITION BY session_id ORDER BY event_at_utc) AS prev_pos
        FROM main_staging.stg_playback_events
       WHERE event_type = 'heartbeat'),
    d AS (
      SELECT date_diff('second', prev_ts, event_at_utc) AS time_delta,
             position_seconds - prev_pos                AS pos_delta
        FROM hb WHERE prev_ts IS NOT NULL)
    SELECT time_delta, pos_delta, count(*) AS occurrences,
           CASE WHEN pos_delta = time_delta AND time_delta = 60 THEN 'normal playback'
                WHEN pos_delta = time_delta                     THEN 'dropped heartbeat(s), playhead kept pace'
                WHEN pos_delta = 0                              THEN 'STALLED (buffer or true pause)'
                WHEN pos_delta > time_delta                     THEN 'SEEK FORWARD'
                WHEN pos_delta < time_delta                     THEN 'playhead fell behind clock'
                ELSE 'other' END AS interpretation
      FROM d GROUP BY 1,2 ORDER BY 3 DESC LIMIT 25
    """,
)

show(
    "SUMMARY — how often does the playhead diverge from the clock at all?",
    """
    WITH hb AS (
      SELECT session_id, event_at_utc, position_seconds,
             lag(event_at_utc)     OVER (PARTITION BY session_id ORDER BY event_at_utc) AS prev_ts,
             lag(position_seconds) OVER (PARTITION BY session_id ORDER BY event_at_utc) AS prev_pos
        FROM main_staging.stg_playback_events
       WHERE event_type = 'heartbeat'),
    d AS (
      SELECT session_id,
             date_diff('second', prev_ts, event_at_utc) AS time_delta,
             position_seconds - prev_pos                AS pos_delta
        FROM hb WHERE prev_ts IS NOT NULL)
    SELECT count(*)                                        AS intervals,
           count(*) FILTER (WHERE pos_delta = time_delta)   AS playhead_tracks_clock,
           count(*) FILTER (WHERE pos_delta <> time_delta)  AS diverges,
           count(DISTINCT session_id) FILTER (WHERE pos_delta <> time_delta) AS sessions_with_divergence
      FROM d
    """,
)

# ---------------------------------------------- do heartbeats fire during buffer?
show(
    "BUFFER — do heartbeats keep firing across a buffer event, and does position stall?",
    """
    WITH seq AS (
      SELECT session_id, event_type, event_at_utc, position_seconds,
             lead(event_type)        OVER (PARTITION BY session_id ORDER BY event_at_utc) AS next_type,
             lead(event_at_utc)      OVER (PARTITION BY session_id ORDER BY event_at_utc) AS next_ts,
             lead(position_seconds)  OVER (PARTITION BY session_id ORDER BY event_at_utc) AS next_pos
        FROM main_staging.stg_playback_events)
    SELECT next_type AS event_after_buffer,
           count(*) AS occurrences,
           round(avg(date_diff('second', event_at_utc, next_ts)), 1) AS avg_time_gap,
           round(avg(next_pos - position_seconds), 1)                AS avg_position_gap
      FROM seq WHERE event_type = 'buffer' AND next_type IS NOT NULL
     GROUP BY 1 ORDER BY 2 DESC
    """,
)

show(
    "BUFFER — is position ever stalled around a buffer? (would make buffer detectable)",
    """
    WITH seq AS (
      SELECT session_id, event_type, event_at_utc, position_seconds,
             lag(position_seconds)  OVER (PARTITION BY session_id ORDER BY event_at_utc) AS prev_pos,
             lag(event_at_utc)      OVER (PARTITION BY session_id ORDER BY event_at_utc) AS prev_ts
        FROM main_staging.stg_playback_events)
    SELECT event_type,
           count(*) AS events,
           count(*) FILTER (WHERE position_seconds = prev_pos) AS position_stalled,
           round(avg(position_seconds - prev_pos), 2) AS avg_pos_advance,
           round(avg(date_diff('second', prev_ts, event_at_utc)), 2) AS avg_time_advance
      FROM seq WHERE prev_pos IS NOT NULL
     GROUP BY 1 ORDER BY 1
    """,
)

# ---------------------------------------------- irregular / start-stop sessions
show(
    "IRREGULARITY — sessions whose heartbeat cadence is not uniformly 60s",
    """
    WITH hb AS (
      SELECT session_id, position_seconds,
             position_seconds - lag(position_seconds)
               OVER (PARTITION BY session_id ORDER BY event_at_utc) AS pos_gap
        FROM main_staging.stg_playback_events WHERE event_type = 'heartbeat'),
    per_session AS (
      SELECT session_id,
             count(*) FILTER (WHERE pos_gap IS NOT NULL)              AS intervals,
             count(*) FILTER (WHERE pos_gap <> 60)                    AS irregular_intervals,
             count(*) FILTER (WHERE pos_gap = 0)                      AS zero_gaps
        FROM hb GROUP BY 1)
    SELECT CASE WHEN irregular_intervals = 0 THEN 'a. perfectly regular 60s'
                WHEN irregular_intervals = 1 THEN 'b. one irregular interval'
                WHEN irregular_intervals <= 3 THEN 'c. 2-3 irregular'
                ELSE 'd. 4+ irregular' END AS pattern,
           count(*) AS sessions,
           sum(zero_gaps) AS total_zero_gap_intervals
      FROM per_session GROUP BY 1 ORDER BY 1
    """,
)

show(
    "ZERO-GAP HEARTBEATS — same position twice. Duplicate emit, or a real stall?",
    """
    WITH hb AS (
      SELECT session_id, event_at_utc, position_seconds,
             lag(event_at_utc)     OVER (PARTITION BY session_id ORDER BY event_at_utc) AS prev_ts,
             lag(position_seconds) OVER (PARTITION BY session_id ORDER BY event_at_utc) AS prev_pos
        FROM main_staging.stg_playback_events WHERE event_type = 'heartbeat')
    SELECT date_diff('second', prev_ts, event_at_utc) AS time_gap_at_same_position,
           count(*) AS occurrences
      FROM hb WHERE position_seconds = prev_pos
     GROUP BY 1 ORDER BY 2 DESC LIMIT 10
    """,
)

con.close()
print("\n" + "=" * 78)
print("done")
