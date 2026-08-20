"""Profiling pass 5 — is a pause-then-resume a de facto seek, and are concurrent subs real?

Question 1. If a pause at playhead position P is followed by an event at a position well
beyond P, the playhead moved while playback was stopped -- which is a seek in everything but
name, even though no seek event exists. The earlier "resumed past pause" number did NOT show
this: it compared the session max to the pause position, which any continued playback
satisfies. This measures the position delta from the pause event to the NEXT event.

Question 2. 391 overlapping subscription pairs exist, but overlap between a free trial and a
paid plan is uninteresting (someone converting early). Overlap between two PAID plans is a
real modelling problem. This splits them.

Runs against the staging views, so timestamps are normalized.

Run: .venv/Scripts/python.exe scripts/profile_pause_seek.py
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
    "main_staging.stg_subscriptions",
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


# ============================================================ sanity: is time monotonic with position?
show(
    "SEQUENCE SANITY — within a session, does event time advance with playhead position?",
    """
    WITH ordered AS (
      SELECT session_id, event_at_utc, position_seconds,
             lag(position_seconds) OVER (PARTITION BY session_id ORDER BY event_at_utc) AS prev_pos,
             lag(event_at_utc)     OVER (PARTITION BY session_id ORDER BY event_at_utc) AS prev_ts
        FROM main_staging.stg_playback_events)
    SELECT count(*) AS transitions,
           count(*) FILTER (WHERE position_seconds < prev_pos) AS position_goes_backwards,
           count(*) FILTER (WHERE position_seconds = prev_pos) AS position_unchanged
      FROM ordered WHERE prev_pos IS NOT NULL
    """,
)

# ============================================================ the actual seek question
show(
    "PAUSE -> NEXT EVENT — how far does the playhead move across the pause?",
    """
    WITH seq AS (
      SELECT session_id, event_type, event_at_utc, position_seconds,
             lead(position_seconds) OVER (PARTITION BY session_id ORDER BY event_at_utc, position_seconds) AS next_pos,
             lead(event_type)       OVER (PARTITION BY session_id ORDER BY event_at_utc, position_seconds) AS next_type
        FROM main_staging.stg_playback_events),
    pauses AS (
      SELECT session_id, position_seconds AS pause_pos, next_pos, next_type,
             next_pos - position_seconds AS jump
        FROM seq WHERE event_type = 'pause' AND next_pos IS NOT NULL)
    SELECT CASE
             WHEN jump <  0   THEN 'a. backwards (rewind)'
             WHEN jump =  0   THEN 'b. same position (true pause)'
             WHEN jump <= 60  THEN 'c. +1..60s (one heartbeat interval)'
             WHEN jump <= 300 THEN 'd. +61..300s'
             ELSE                  'e. +300s or more (clear jump)'
           END AS playhead_move_across_pause,
           count(*) AS pauses,
           round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
      FROM pauses GROUP BY 1 ORDER BY 1
    """,
)

show(
    "PAUSE -> NEXT EVENT — what event type actually follows a pause?",
    """
    WITH seq AS (
      SELECT session_id, event_type,
             lead(event_type) OVER (PARTITION BY session_id ORDER BY event_at_utc, position_seconds) AS next_type
        FROM main_staging.stg_playback_events)
    SELECT next_type AS event_following_a_pause, count(*) AS occurrences
      FROM seq WHERE event_type = 'pause' AND next_type IS NOT NULL
     GROUP BY 1 ORDER BY 2 DESC
    """,
)

show(
    "IS THERE A RESUMING 'play' AT ALL? — play events per session",
    """
    SELECT n_play, count(*) AS sessions
      FROM (SELECT session_id, count(*) FILTER (WHERE event_type = 'play') AS n_play
              FROM main_staging.stg_playback_events GROUP BY 1)
     GROUP BY 1 ORDER BY 1
    """,
)

show(
    "WORKED EXAMPLE — one paused session, in full event order",
    """
    SELECT event_type, event_at_utc, position_seconds
      FROM main_staging.stg_playback_events
     WHERE session_id = (
       SELECT session_id FROM main_staging.stg_playback_events
        WHERE event_type = 'pause' GROUP BY 1
        HAVING count(*) FILTER (WHERE event_type = 'pause') = 1
        ORDER BY session_id LIMIT 1)
     ORDER BY event_at_utc, position_seconds
     LIMIT 40
    """,
)

# ============================================================ concurrent PAID subscriptions
show(
    "CONCURRENT SUBSCRIPTIONS — trial-vs-paid overlap, or two genuinely paid plans?",
    """
    WITH span AS (
      SELECT user_id, subscription_id,
             min(effective_at_utc) AS first_ts,
             max(effective_at_utc) AS last_ts,
             max(case when plan_type in ('monthly','annual') then 1 else 0 end) AS has_paid_plan,
             max(case when plan_type = 'free_trial'          then 1 else 0 end) AS has_trial
        FROM main_staging.stg_subscriptions GROUP BY 1,2)
    SELECT CASE WHEN a.has_paid_plan = 1 AND b.has_paid_plan = 1 THEN 'BOTH PAID (real problem)'
                WHEN a.has_paid_plan = 1 OR  b.has_paid_plan = 1 THEN 'one paid, one trial-only'
                ELSE                                                  'both trial-only' END AS overlap_kind,
           count(*) AS overlapping_pairs,
           count(DISTINCT a.user_id) AS users
      FROM span a JOIN span b
        ON a.user_id = b.user_id AND a.subscription_id < b.subscription_id
       AND a.first_ts <= b.last_ts AND b.first_ts <= a.last_ts
     GROUP BY 1 ORDER BY 2 DESC
    """,
)

show(
    "CONCURRENT PAID — do the paid windows really overlap while BOTH are active?",
    """
    WITH paid_span AS (
      SELECT user_id, subscription_id,
             min(effective_at_utc) FILTER (WHERE status = 'active') AS active_from,
             coalesce(
               min(effective_at_utc) FILTER (WHERE status in ('canceled','expired')),
               timestamp '2099-01-01') AS active_to
        FROM main_staging.stg_subscriptions
       WHERE plan_type in ('monthly','annual')
       GROUP BY 1,2)
    SELECT count(*) AS truly_concurrent_paid_pairs,
           count(DISTINCT a.user_id) AS users_affected
      FROM paid_span a JOIN paid_span b
        ON a.user_id = b.user_id AND a.subscription_id < b.subscription_id
       AND a.active_from IS NOT NULL AND b.active_from IS NOT NULL
       AND a.active_from < b.active_to AND b.active_from < a.active_to
    """,
)

con.close()
print("\n" + "=" * 78)
print("done")
