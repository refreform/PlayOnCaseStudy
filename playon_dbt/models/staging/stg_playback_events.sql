/*
    Grain: one row per playback telemetry event, deduplicated.

    DEDUPLICATION -- 600 event_ids appear twice in raw, and in every one of those 600 cases
    the two rows are byte-identical across all nine remaining columns (verified 2026-08-18).
    That is what makes it safe to keep one arbitrarily: there is no information in the second
    copy and no tie-break to get wrong. Had the duplicates conflicted, this would need a
    documented precedence rule instead, and the surviving row would be a real choice.

    216,045 raw rows -> 215,445 here. The 600-row drop is the only row-count change in this
    model and is reconciled by a singular test in tests/.

    ORPHANED FOREIGN KEYS -- RETAINED HERE BY DESIGN. This model keeps:

      * 4,496 rows (2.1%) whose asset_id is absent from asset_catalog, spanning 38 assets
      * 1,458 rows whose user_id is absent from users, spanning 42 accounts

    Staging's job is to clean types and encodings, not to decide what counts. Dropping
    orphans here would silently delete real viewing from the only place it is recorded, and
    the loss would be invisible to anyone reading a downstream model. They are filtered in
    `marts/data/fct_session` instead, where the exclusion is explicit and its row impact is
    reconciled. This is a KNOWN ISSUE, not an oversight: the underlying cause -- a catalog
    extract that does not cover every asset referenced by telemetry -- is an open question
    for the streaming engineering team.

    NULL user_id is NOT an orphan and is not filtered anywhere: 35,230 rows (16.3%) are
    pre-sign-in viewing, which the data dictionary documents as expected. Anonymity is a
    whole-session property (978 fully anonymous sessions, 5,022 fully identified, zero
    mixed), so it can be handled cleanly at session grain downstream.
*/

with source as (

    select * from {{ source('raw', 'playback_events') }}

),

deduplicated as (

    select *
    from source
    qualify row_number() over (
        partition by event_id
        -- Arbitrary but deterministic: the duplicate rows are identical, so any stable
        -- ordering yields the same result on every run.
        order by session_id, event_ts, position_seconds
    ) = 1

),

cleaned as (

    select
        cast(event_id as bigint)                    as event_id,
        session_id                                  as session_id,
        cast(user_id as bigint)                     as user_id,
        cast(asset_id as bigint)                    as asset_id,

        event_type                                  as event_type,

        {{ normalize_timestamp('event_ts') }}       as event_at_utc,
        {{ timestamp_source_format('event_ts') }}   as event_ts_source_format,

        cast(position_seconds as double)            as position_seconds,
        device_type                                 as device_type,
        app_version                                 as app_version,
        cast(bitrate_kbps as integer)               as bitrate_kbps,

        -- Anonymity is a session-level property; surfacing it per row keeps downstream
        -- filters honest about what they are excluding.
        user_id is null                             as is_anonymous_view

    from deduplicated

)

select * from cleaned
