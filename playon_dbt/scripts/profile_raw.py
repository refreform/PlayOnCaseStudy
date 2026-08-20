"""Profile the raw PrepCast extracts. Read-only against the `raw` schema.

Aggregate, don't eyeball: playback_events is 216k rows. Everything here is a query whose result
is small enough to read, and each block is written to answer a specific question from
dev_docs/project/roadmap.md phase 1.

Run: .venv/Scripts/python.exe scripts/profile_raw.py
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


# ---------------------------------------------------------------- key uniqueness
show(
    "KEY UNIQUENESS — is the declared grain real?",
    """
    SELECT 'playback_events.event_id'  AS key, count(*) AS rows,
           count(DISTINCT event_id) AS distinct_vals,
           count(*) - count(DISTINCT event_id) AS surplus_rows
      FROM raw.playback_events
    UNION ALL
    SELECT 'users.user_id', count(*), count(DISTINCT user_id),
           count(*) - count(DISTINCT user_id) FROM raw.users
    UNION ALL
    SELECT 'asset_catalog.asset_id', count(*), count(DISTINCT asset_id),
           count(*) - count(DISTINCT asset_id) FROM raw.asset_catalog
    UNION ALL
    SELECT 'subscriptions.subscription_id', count(*), count(DISTINCT subscription_id),
           count(*) - count(DISTINCT subscription_id) FROM raw.subscriptions
    UNION ALL
    SELECT 'subscriptions.(sub_id, eff_ts)', count(*),
           count(DISTINCT (subscription_id, event_effective_ts)),
           count(*) - count(DISTINCT (subscription_id, event_effective_ts))
      FROM raw.subscriptions
    """,
)

# ---------------------------------------------------------------- event_ts formats
show(
    "event_ts ENCODINGS — how many formats are actually in there?",
    """
    SELECT CASE
             WHEN event_ts IS NULL              THEN '1. NULL'
             WHEN event_ts = ''                 THEN '2. empty string'
             WHEN regexp_matches(event_ts, '^[0-9]+$')                  THEN '3. epoch digits'
             WHEN regexp_matches(event_ts, '^\\d{4}-\\d{2}-\\d{2}T.*Z$') THEN '4. ISO-8601 Z'
             WHEN regexp_matches(event_ts, '^\\d{4}-\\d{2}-\\d{2}T')     THEN '5. ISO no Z'
             WHEN regexp_matches(event_ts, '^\\d{4}-\\d{2}-\\d{2} ')     THEN '6. ISO space sep'
             ELSE '7. OTHER'
           END AS ts_shape,
           count(*) AS rows,
           round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct,
           min(event_ts) AS min_example, max(event_ts) AS max_example
      FROM raw.playback_events
     GROUP BY 1 ORDER BY 1
    """,
)

# ---------------------------------------------------------------- nulls / blanks
show(
    "NULL & BLANK RATES — playback_events",
    """
    SELECT col, nulls, blanks, round(100.0*(nulls+blanks)/216045, 2) AS pct_missing FROM (
      SELECT 'user_id' AS col, count(*) FILTER (WHERE user_id IS NULL) AS nulls,
             count(*) FILTER (WHERE user_id = '') AS blanks FROM raw.playback_events
      UNION ALL SELECT 'session_id', count(*) FILTER (WHERE session_id IS NULL),
             count(*) FILTER (WHERE session_id = '') FROM raw.playback_events
      UNION ALL SELECT 'asset_id', count(*) FILTER (WHERE asset_id IS NULL),
             count(*) FILTER (WHERE asset_id = '') FROM raw.playback_events
      UNION ALL SELECT 'event_type', count(*) FILTER (WHERE event_type IS NULL),
             count(*) FILTER (WHERE event_type = '') FROM raw.playback_events
      UNION ALL SELECT 'event_ts', count(*) FILTER (WHERE event_ts IS NULL),
             count(*) FILTER (WHERE event_ts = '') FROM raw.playback_events
      UNION ALL SELECT 'position_seconds', count(*) FILTER (WHERE position_seconds IS NULL),
             count(*) FILTER (WHERE position_seconds = '') FROM raw.playback_events
      UNION ALL SELECT 'device_type', count(*) FILTER (WHERE device_type IS NULL),
             count(*) FILTER (WHERE device_type = '') FROM raw.playback_events
      UNION ALL SELECT 'app_version', count(*) FILTER (WHERE app_version IS NULL),
             count(*) FILTER (WHERE app_version = '') FROM raw.playback_events
      UNION ALL SELECT 'bitrate_kbps', count(*) FILTER (WHERE bitrate_kbps IS NULL),
             count(*) FILTER (WHERE bitrate_kbps = '') FROM raw.playback_events
    ) ORDER BY pct_missing DESC
    """,
)

# ---------------------------------------------------------------- categoricals
for col, tbl in [
    ("event_type", "playback_events"),
    ("device_type", "playback_events"),
    ("app_version", "playback_events"),
    ("asset_type", "asset_catalog"),
    ("sport", "asset_catalog"),
    ("status", "subscriptions"),
    ("plan_type", "subscriptions"),
    ("currency", "subscriptions"),
    ("acquisition_channel", "users"),
]:
    show(
        f"CATEGORICAL — {tbl}.{col}",
        f"SELECT {col} AS value, count(*) AS rows FROM raw.{tbl} "
        f"GROUP BY 1 ORDER BY 2 DESC LIMIT 40",
    )

show(
    "CATEGORICAL — users.home_state (cardinality + oddities)",
    """
    SELECT count(DISTINCT home_state) AS distinct_states,
           count(*) FILTER (WHERE length(home_state) <> 2) AS not_two_chars,
           count(*) FILTER (WHERE home_state <> upper(home_state)) AS not_upper,
           count(*) FILTER (WHERE home_state IS NULL OR home_state = '') AS missing
      FROM raw.users
    """,
)

# ---------------------------------------------------------------- referential integrity
show(
    "FOREIGN KEYS — orphan rates",
    """
    SELECT 'playback_events.asset_id -> asset_catalog' AS fk,
           count(*) AS child_rows,
           count(*) FILTER (WHERE a.asset_id IS NULL) AS orphans
      FROM raw.playback_events p LEFT JOIN raw.asset_catalog a USING (asset_id)
    UNION ALL
    SELECT 'playback_events.user_id -> users (non-blank only)',
           count(*), count(*) FILTER (WHERE u.user_id IS NULL)
      FROM raw.playback_events p LEFT JOIN raw.users u USING (user_id)
     WHERE p.user_id IS NOT NULL AND p.user_id <> ''
    UNION ALL
    SELECT 'subscriptions.user_id -> users',
           count(*), count(*) FILTER (WHERE u.user_id IS NULL)
      FROM raw.subscriptions s LEFT JOIN raw.users u USING (user_id)
    """,
)

# ---------------------------------------------------------------- numeric sanity
show(
    "NUMERIC SANITY — non-numeric, negative, and extreme values",
    """
    SELECT 'playback_events.position_seconds' AS col,
           count(*) FILTER (WHERE NOT regexp_matches(position_seconds, '^-?[0-9.]+$')) AS non_numeric,
           count(*) FILTER (WHERE TRY_CAST(position_seconds AS DOUBLE) < 0) AS negative,
           min(TRY_CAST(position_seconds AS DOUBLE)) AS min_val,
           max(TRY_CAST(position_seconds AS DOUBLE)) AS max_val
      FROM raw.playback_events
    UNION ALL
    SELECT 'playback_events.bitrate_kbps',
           count(*) FILTER (WHERE NOT regexp_matches(bitrate_kbps, '^-?[0-9.]+$')),
           count(*) FILTER (WHERE TRY_CAST(bitrate_kbps AS DOUBLE) < 0),
           min(TRY_CAST(bitrate_kbps AS DOUBLE)), max(TRY_CAST(bitrate_kbps AS DOUBLE))
      FROM raw.playback_events
    UNION ALL
    SELECT 'asset_catalog.duration_seconds',
           count(*) FILTER (WHERE NOT regexp_matches(duration_seconds, '^-?[0-9.]+$')),
           count(*) FILTER (WHERE TRY_CAST(duration_seconds AS DOUBLE) < 0),
           min(TRY_CAST(duration_seconds AS DOUBLE)), max(TRY_CAST(duration_seconds AS DOUBLE))
      FROM raw.asset_catalog
    UNION ALL
    SELECT 'subscriptions.mrr_amount',
           count(*) FILTER (WHERE NOT regexp_matches(mrr_amount, '^-?[0-9.]+$')),
           count(*) FILTER (WHERE TRY_CAST(mrr_amount AS DOUBLE) < 0),
           min(TRY_CAST(mrr_amount AS DOUBLE)), max(TRY_CAST(mrr_amount AS DOUBLE))
      FROM raw.subscriptions
    """,
)

# ---------------------------------------------------------------- session shape
show(
    "SESSIONS — volume and composition",
    """
    SELECT count(DISTINCT session_id) AS sessions,
           count(*) AS events,
           round(count(*)::DOUBLE / count(DISTINCT session_id), 2) AS events_per_session,
           count(DISTINCT user_id) AS distinct_users,
           count(DISTINCT asset_id) AS distinct_assets
      FROM raw.playback_events
    """,
)

show(
    "SESSIONS — does a session ever span multiple users or assets? (fan-out risk)",
    """
    SELECT count(*) FILTER (WHERE n_assets > 1) AS sessions_multi_asset,
           count(*) FILTER (WHERE n_users  > 1) AS sessions_multi_user,
           count(*) AS total_sessions
      FROM (SELECT session_id,
                   count(DISTINCT asset_id) AS n_assets,
                   count(DISTINCT user_id)  AS n_users
              FROM raw.playback_events GROUP BY 1)
    """,
)

show(
    "SESSIONS — event_type composition per session",
    """
    SELECT has_play, has_stop, count(*) AS sessions
      FROM (SELECT session_id,
                   max(CASE WHEN event_type = 'play' THEN 1 ELSE 0 END) AS has_play,
                   max(CASE WHEN event_type = 'stop' THEN 1 ELSE 0 END) AS has_stop
              FROM raw.playback_events GROUP BY 1)
     GROUP BY 1,2 ORDER BY 1 DESC, 2 DESC
    """,
)

# ---------------------------------------------------------------- subscriptions shape
show(
    "SUBSCRIPTIONS — rows per subscription, and subs per user",
    """
    SELECT 'rows per subscription_id' AS metric, min(n) AS min, max(n) AS max,
           round(avg(n), 2) AS avg, count(*) AS n_entities
      FROM (SELECT subscription_id, count(*) AS n FROM raw.subscriptions GROUP BY 1)
    UNION ALL
    SELECT 'subscriptions per user_id', min(n), max(n), round(avg(n), 2), count(*)
      FROM (SELECT user_id, count(DISTINCT subscription_id) AS n
              FROM raw.subscriptions GROUP BY 1)
    """,
)

show(
    "SUBSCRIPTIONS — status x plan_type matrix",
    """
    SELECT status, plan_type, count(*) AS rows,
           count(DISTINCT mrr_amount) AS distinct_mrr, min(mrr_amount) AS min_mrr,
           max(mrr_amount) AS max_mrr
      FROM raw.subscriptions GROUP BY 1,2 ORDER BY 1,2
    """,
)

show(
    "COVERAGE — how many users actually subscribe / watch?",
    """
    SELECT (SELECT count(*) FROM raw.users) AS users_total,
           (SELECT count(DISTINCT user_id) FROM raw.subscriptions) AS users_with_sub,
           (SELECT count(DISTINCT user_id) FROM raw.playback_events
             WHERE user_id IS NOT NULL AND user_id <> '') AS users_with_playback
    """,
)

con.close()
print("\n" + "=" * 78)
print("done")
