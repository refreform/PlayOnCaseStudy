/*
    The deduplication in stg_playback_events keeps one row per event_id arbitrarily. That is
    only safe because the duplicate copies are byte-identical: there is no information in the
    second copy and therefore no tie-break to get wrong.

    Verified by hand on 2026-08-18 -- 600 duplicated event_ids, zero with conflicting content
    -- but a hand check is a claim about one extract, not a property of the pipeline. This
    test makes it a property. If a future extract ever produces two DIFFERENT rows sharing an
    event_id, the qualify in stg_playback_events would silently pick one and nothing else in
    the project would notice.

    Fails with the offending event_ids. The fix is not to make this test pass -- it is to
    write down a precedence rule (latest event_ts wins, highest position_seconds wins, ...)
    and make the surviving row a documented choice.
*/

with hashed as (

    select
        event_id,
        {{ dbt_utils.generate_surrogate_key([
            'session_id',
            'user_id',
            'asset_id',
            'event_type',
            'event_ts',
            'position_seconds',
            'device_type',
            'app_version',
            'bitrate_kbps'
        ]) }} as row_hash

    from {{ source('raw', 'playback_events') }}

),

per_event_id as (

    select
        event_id,
        count(*)                as copies,
        count(distinct row_hash) as distinct_versions

    from hashed
    group by event_id

)

select
    event_id,
    copies,
    distinct_versions
from per_event_id
where copies > 1
  and distinct_versions > 1
