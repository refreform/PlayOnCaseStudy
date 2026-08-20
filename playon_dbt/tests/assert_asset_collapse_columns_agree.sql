/*
    `dim_asset` collapses the 12 `asset_id`s that cover two catalog rows each (a game and its
    "(Replay)") down to one row per `asset_id`, using max() on five columns. That is only
    deduplication -- rather than an arbitrary pick between conflicting values -- because the
    colliding pairs are identical on exactly those five columns.

    That was verified by hand across all 12 pairs on 2026-08-19. A hand check is a claim about
    one extract, not a property of the pipeline: the identical argument is already made by
    assert_playback_events_duplicates_are_identical, and the asset collapse rests on the same
    kind of claim with no equivalent guard. This is that guard.

    If a future extract ever produces a colliding pair that DISAGREES on one of these columns,
    max() would silently pick the alphabetically or numerically larger value and every other
    test in the project would still pass -- `dim_asset` would remain unique on asset_id, its
    row count would be unchanged, and the wrong sport or runtime would flow into every session
    that joins it.

    The fix is not to make this test pass. It is to decide which row wins and say so in SQL --
    at which point the surviving value is a documented choice rather than an accident of
    collation order.

    Returns zero rows when healthy.
*/

select
    asset_id,
    count(*)                                        as catalog_rows,
    count(distinct sport)                           as distinct_sports,
    count(distinct home_school)                     as distinct_home_schools,
    count(distinct away_school)                     as distinct_away_schools,
    count(distinct scheduled_start_at_utc)          as distinct_starts,
    -- coalesced because count(distinct) skips NULLs: two rows, one with a nulled invalid
    -- runtime and one without, would otherwise read as agreeing.
    count(distinct coalesce(duration_seconds, -1))  as distinct_durations

from {{ ref('stg_asset_catalog') }}
group by asset_id
having count(distinct sport)                          > 1
    or count(distinct home_school)                    > 1
    or count(distinct away_school)                    > 1
    or count(distinct scheduled_start_at_utc)         > 1
    or count(distinct coalesce(duration_seconds, -1)) > 1
