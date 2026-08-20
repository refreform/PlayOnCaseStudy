-- Scratch queries for the DuckDB UI (http://localhost:4213).
-- Not part of the dbt build -- paste these in and edit freely.
--
-- Each block re-derives a claim from the profiling passes, so you can check the numbers
-- yourself rather than taking them from a summary. The finding each one reproduces is noted.

-- ---------------------------------------------------------------- the 12 duplicated asset_ids
-- Finding: not corrupt duplicates -- each pair is a game and its "(Replay)", sharing one id.
SELECT asset_id, title, asset_type, sport, home_school, away_school,
       scheduled_start_ts, duration_seconds
  FROM raw.asset_catalog
 WHERE asset_id IN (SELECT asset_id FROM raw.asset_catalog GROUP BY 1 HAVING count(*) > 1)
 ORDER BY asset_id, title;

-- How much playback is actually stranded on those ambiguous ids?
SELECT count(*) AS events, count(DISTINCT session_id) AS sessions
  FROM raw.playback_events
 WHERE asset_id IN (SELECT asset_id FROM raw.asset_catalog GROUP BY 1 HAVING count(*) > 1);

-- ---------------------------------------------------------------- fan-out, live
-- Finding: 216,045 -> 218,782 (left join) or 214,286 (inner). Both wrong.
SELECT (SELECT count(*) FROM raw.playback_events)                              AS before_join,
       (SELECT count(*) FROM raw.playback_events JOIN raw.asset_catalog USING (asset_id))
                                                                               AS after_inner,
       (SELECT count(*) FROM raw.playback_events LEFT JOIN raw.asset_catalog USING (asset_id))
                                                                               AS after_left;

-- ---------------------------------------------------------------- three timestamp encodings
-- Finding: 54.9% ISO-8601 with Z, 25.5% space-separated with NO timezone, 19.7% epoch seconds.
SELECT CASE WHEN regexp_matches(event_ts, '^[0-9]+$') THEN 'epoch seconds'
            WHEN event_ts LIKE '%T%Z'                 THEN 'ISO-8601 Z'
            ELSE                                           'ISO space-separated (no tz)' END AS shape,
       count(*) AS rows,
       round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct,
       min(event_ts) AS example_min, max(event_ts) AS example_max
  FROM raw.playback_events GROUP BY 1 ORDER BY 2 DESC;

-- Same problem in the subscription log: 1,225 of 8,014 rows are the timezone-less form.
SELECT CASE WHEN event_effective_ts LIKE '%T%Z' THEN 'ISO-8601 Z'
            ELSE 'ISO space-separated (no tz)' END AS shape, count(*) AS rows
  FROM raw.subscriptions GROUP BY 1;

-- ---------------------------------------------------------------- sport categorical mess
-- Finding: 24 raw variants for 10 real sports -- casing, abbreviations, lowercase.
SELECT sport, count(*) AS assets FROM raw.asset_catalog GROUP BY 1 ORDER BY lower(sport), sport;

-- ---------------------------------------------------------------- broken durations
-- Finding: 20 assets at -600, -1, or 0. This is the completion-ratio denominator.
SELECT asset_id, asset_type, sport, title, duration_seconds
  FROM raw.asset_catalog
 WHERE TRY_CAST(duration_seconds AS DOUBLE) <= 0
 ORDER BY TRY_CAST(duration_seconds AS DOUBLE), asset_id;

-- ---------------------------------------------------------------- currency + annual MRR
-- Finding: 79 non-USD rows make mrr_amount non-summable; annual plans carry 79.99 in a
-- column named *monthly* recurring revenue (79.99/12 ~ 6.67).
SELECT currency, plan_type, count(*) AS rows, min(mrr_amount) AS amt
  FROM raw.subscriptions GROUP BY 1,2 ORDER BY 1,2;

-- ---------------------------------------------------------------- subscription lifecycles
-- Finding: rows are appended per status change; separately, users can hold several
-- subscriptions, and 391 pairs across 326 users genuinely overlap in time.
SELECT path, count(*) AS subscriptions FROM (
  SELECT subscription_id, string_agg(status, ' -> ' ORDER BY event_effective_ts) AS path
    FROM raw.subscriptions GROUP BY 1) GROUP BY 1 ORDER BY 2 DESC;

-- Users holding overlapping (concurrent) subscriptions.
WITH span AS (
  SELECT user_id, subscription_id,
         min(TRY_CAST(event_effective_ts AS TIMESTAMP)) AS first_ts,
         max(TRY_CAST(event_effective_ts AS TIMESTAMP)) AS last_ts
    FROM raw.subscriptions GROUP BY 1,2)
SELECT a.user_id, a.subscription_id AS sub_a, b.subscription_id AS sub_b,
       a.first_ts AS a_from, a.last_ts AS a_to, b.first_ts AS b_from, b.last_ts AS b_to
  FROM span a JOIN span b
    ON a.user_id = b.user_id AND a.subscription_id < b.subscription_id
   AND a.first_ts <= b.last_ts AND b.first_ts <= a.last_ts
 ORDER BY a.user_id LIMIT 50;

-- ---------------------------------------------------------------- engagement signals
-- Finding: heartbeats fire every 60s; ~5.8% of intervals show a dropped beat.
WITH hb AS (
  SELECT session_id, TRY_CAST(position_seconds AS DOUBLE) AS pos
    FROM raw.playback_events WHERE event_type = 'heartbeat'),
gaps AS (
  SELECT pos - lag(pos) OVER (PARTITION BY session_id ORDER BY pos) AS gap_seconds
    FROM hb)
SELECT gap_seconds, count(*) AS occurrences
  FROM gaps WHERE gap_seconds IS NOT NULL
 GROUP BY 1 ORDER BY 2 DESC;

-- Finding: completion ratio is bimodal, with an empty valley between 0.2 and 0.4.
SELECT floor(least(max_pos / dur, 1.0) * 10) / 10.0 AS completion_bucket,
       count(*) AS sessions
  FROM (SELECT p.session_id,
               max(TRY_CAST(p.position_seconds AS DOUBLE)) AS max_pos,
               max(TRY_CAST(a.duration_seconds AS DOUBLE)) AS dur
          FROM raw.playback_events p
          JOIN (SELECT DISTINCT ON (asset_id) asset_id, duration_seconds
                  FROM raw.asset_catalog) a USING (asset_id)
         GROUP BY 1)
 WHERE dur > 0 GROUP BY 1 ORDER BY 1;

-- Finding: stop fires ~244s later than the last heartbeat in 5,918 of 6,000 sessions.
SELECT CASE WHEN stop_pos = last_hb THEN 'identical'
            WHEN stop_pos > last_hb THEN 'stop later'
            ELSE 'stop earlier' END AS relation,
       count(*) AS sessions, round(avg(stop_pos - last_hb), 1) AS avg_gap_seconds
  FROM (SELECT session_id,
               max(TRY_CAST(position_seconds AS DOUBLE))
                 FILTER (WHERE event_type = 'stop')      AS stop_pos,
               max(TRY_CAST(position_seconds AS DOUBLE))
                 FILTER (WHERE event_type = 'heartbeat') AS last_hb
          FROM raw.playback_events GROUP BY 1)
 GROUP BY 1 ORDER BY 2 DESC;
