/*
    Grain: one row per viewing session. 5,739 rows.

    NAMED `fct_`, NOT `dim_`. This carries measures at a transaction grain -- watch_minutes,
    event_count, buffer_events, completion_pct -- which makes it a fact table, whatever the
    word "session" suggests. It was called `dim_session` until WP-009. The prefix is not
    decoration: a reviewer reading `dim_` expects attributes to describe rows with, not
    measures to aggregate, and picks the wrong join grain accordingly.

    DATA-OWNED. Sessionization of the raw event stream, and nothing else. Every column here
    is a fact about what the player reported -- how long, how far, on what device. No judgement
    about what any of it means.

    That boundary is the point. An earlier version of this model applied the engaged-view
    threshold here, which would have forced any team adopting it to inherit the Product team's
    definition of engagement whether they agreed with it or not. The classification now lives in
    `product/fct_session_engagement`, on the product side of the line, and this model is
    adoptable by anyone consuming PrepCast telemetry.

    Test for which side a model belongs on: if the Product team's definition of engagement changed
    tomorrow, would this model change? Here, no.

    ORPHANS ARE FILTERED HERE. This is the layer the owner designated for it (WP-002 decision 4).
    Staging deliberately keeps every orphan so no data is destroyed and other teams can reach it;
    a mart must not carry rows that cannot be joined to a dimension. What is dropped:

      * sessions whose `asset_id` has no catalog row  -> 123 sessions
      * sessions whose asset has an invalid runtime   -> 138 sessions

    Both are DROPPED rather than routed to an "unknown" dimension member, because without a
    runtime there is no denominator and therefore no completion ratio -- an unknown-member row
    would carry a null metric and pretend to be analysable. The counts are asserted by
    `tests/assert_session_exclusions_reconcile.sql`, so the exclusion can never drift silently.

    **If you need the excluded sessions, they are intact in `stg_playback_events`.** Nothing is
    lost, it is moved out of the analytic path. See `_data__models.yml` for the same
    warning in the documentation surface.

    MEASUREMENT NOTES (each of these was a trap; see dev_docs/domain/engaged-view.md):

      * Completion uses HEARTBEAT positions only. `stop.position_seconds` is not a real playhead
        reading -- it jumps ~237s past the last heartbeat in ~10s of wall time, inflating
        completion ~11%.
      * Watch minutes count DISTINCT heartbeat positions. 2,236 heartbeat pairs share a timestamp
        and position (duplicate emissions that survived event_id deduplication because their ids
        differ); counting rows would overstate watch time by 1.17%.
      * The threshold is var('engaged_view_min_completion_pct'), declared in dbt_project.yml.
*/

with events as (

    select * from {{ ref('stg_playback_events') }}

),

assets as (

    select * from {{ ref('dim_asset') }}

),

known_users as (

    select user_id from {{ ref('stg_users') }}

),

sessioned as (

    select
        e.session_id,

        -- Verified invariant: no session spans two users or two assets, so max() is safe here
        -- rather than a lie. (source-extracts.md 6.6)
        max(e.user_id)                                          as user_id,
        max(e.asset_id)                                         as asset_id,
        bool_and(e.is_anonymous_view)                           as is_anonymous_session,

        min(e.event_at_utc)                                     as session_start_at_utc,
        max(e.event_at_utc)                                     as session_end_at_utc,

        count(*)                                                as event_count,
        count(distinct e.position_seconds)
            filter (where e.event_type = 'heartbeat')           as watch_minutes,
        count(*) filter (where e.event_type = 'buffer')         as buffer_events,
        max(e.position_seconds)
            filter (where e.event_type = 'heartbeat')           as max_heartbeat_position_seconds,

        max(e.device_type)                                      as device_type,
        max(e.app_version)                                      as app_version,
        max(e.bitrate_kbps)                                     as bitrate_kbps

    from events e
    group by e.session_id

),

joined as (

    select
        s.*,
        a.sport,
        a.duration_seconds                                      as asset_duration_seconds,
        a.has_ambiguous_identity                                as asset_identity_ambiguous,
        /*
            38 sessions carry a user_id absent from the users extract -- the orphan user FK.
            They are NOT anonymous (a user was identified) and NOT attributable (we do not know
            who). Flagged rather than dropped: the viewing is real and belongs in fct_session,
            but it cannot appear in the user-grain fact. Making that explicit here is what stops
            it from vanishing silently at the join, which is exactly what it did before
            assert_fct_user_engagement_grain caught it.
        */
        s.user_id is not null and ku.user_id is null            as has_unknown_user
    from sessioned s
    /*
        INNER JOIN -- this is the orphan filter. dim_asset is one row per asset_id,
        so this join cannot fan out; that is the entire reason that model exists.

        Note the absence of asset_type (LIVE/VOD): dim_asset deliberately does not
        expose it, because it is one of the two columns the 12 colliding asset_ids disagree on.
        Sessions therefore cannot be split by LIVE vs VOD from this path. Accepted because the
        two are behaviourally indistinguishable here; see that model's header.
    */
    join assets a
        on s.asset_id = a.asset_id
    left join known_users ku
        on s.user_id = ku.user_id
    where a.duration_seconds is not null

),

measured as (

    select
        *,
        cast(session_start_at_utc as date)                       as session_date,

        -- The completion RATIO is a fact: watched fraction of the asset's runtime. Where the
        -- threshold sits -- what counts as "engaged" -- is an opinion, and lives in
        -- product/fct_session_engagement. This model deliberately stops short of that line.
        max_heartbeat_position_seconds / asset_duration_seconds  as completion_pct,

        -- Rate, not a count. Buffer counts rise with session length and mislead badly; the
        -- rate is flat at ~0.32 across every engagement level, which is what ruled out quality
        -- of experience as an explanation for abandonment.
        round(buffer_events * 10.0 / nullif(watch_minutes, 0), 3) as buffers_per_10min

    from joined

)

select * from measured
