/*
    Grain: one row per `asset_id`. The join-safe view of the catalog.

    THE PROBLEM. `stg_asset_catalog` is correct at its own grain (one row per distinct asset,
    keyed by `asset_key`) but 12 `asset_id`s cover two assets each -- a game and its "(Replay)".
    Joining playback events on `asset_id` there fans 216,045 rows out to 218,782.

    THE RULE (owner decision, 2026-08-19). This model carries only the columns on which the
    colliding pairs AGREE. Verified across all 12 pairs: `sport`, `home_school`, `away_school`,
    `scheduled_start_at_utc` and `duration_seconds` are identical in 12 of 12. Restricted to
    those columns the pairs are genuine duplicates, so collapsing them is not a judgement call
    or a loss -- it is deduplication of rows that really are the same.

    `title` and `asset_type` are therefore NOT exposed here. An earlier version kept them and
    set them to NULL for the ambiguous 12; that was rejected as worse. Nulling puts a column in
    the model that is sometimes a fact and sometimes an admission, so every consumer has to
    remember which. Omitting the column states the boundary once, in the schema, where it
    cannot be forgotten.

    WHAT THIS COSTS. `asset_type` (LIVE vs VOD) is unambiguous for 838 of 850 assets, and this
    rule withholds it from all of them to stay honest about 12. That is a real cost, accepted
    because the two behave indistinguishably in this data -- median completion at stop is 0.2
    for LIVE and for VOD -- so the analytical loss is close to zero. If that stops being true,
    revisit: the alternative is exposing `asset_type` only where `source_row_count = 1`.

    WHERE TO GET THE FULL ATTRIBUTES. `dim_asset` carries `title` and `asset_type` at
    `asset_key` grain, with full fidelity. It cannot be joined to playback events on `asset_id`
    without fan-out -- that is precisely the information the fact table never captured.
*/

with catalog as (

    select * from {{ ref('stg_asset_catalog') }}

),

collapsed as (

    select
        asset_id,

        -- Verified identical across every colliding pair, so max() here is deduplication,
        -- not an arbitrary pick between conflicting values.
        max(sport)                          as sport,
        max(home_school)                    as home_school,
        max(away_school)                    as away_school,
        max(scheduled_start_at_utc)         as scheduled_start_at_utc,
        max(duration_seconds)               as duration_seconds,
        bool_or(has_invalid_duration)       as has_invalid_duration,

        -- How many catalog rows share this asset_id. >1 means the live/replay collision, and
        -- is the flag a consumer needs before reaching for dim_asset expecting one match.
        count(*)                            as source_row_count,
        count(*) > 1                        as has_ambiguous_identity

    from catalog
    group by asset_id

)

select * from collapsed
