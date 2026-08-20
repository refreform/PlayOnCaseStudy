/*
    Row-count reconciliation: raw.playback_events -> stg_playback_events.

    The staging model makes exactly one deliberate row-count change: it drops 600 rows, the
    second copy of each of the 600 byte-identical duplicate event_ids. Any other delta means
    something was lost that nobody decided to lose -- a failed cast producing a null that a
    later filter dropped, or a join accidentally introduced into a model that should have
    none.

    This is the check that catches silent loss, which generic column tests cannot see.
    Fails if the arithmetic does not hold exactly.
*/

with counts as (

    select
        (select count(*) from {{ source('raw', 'playback_events') }})   as raw_rows,
        (select count(*) from {{ ref('stg_playback_events') }})         as staged_rows,
        (select count(*) - count(distinct event_id)
           from {{ source('raw', 'playback_events') }})                 as expected_dupes_removed

)

select
    raw_rows,
    staged_rows,
    expected_dupes_removed,
    raw_rows - staged_rows as actual_rows_removed
from counts
where raw_rows - staged_rows != expected_dupes_removed
