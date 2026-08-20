/*
    Within one subscription, the type 2 windows must tile its timeline with no gaps and no
    overlaps: each window's valid_to must equal the next window's valid_from.

    A gap means a period where the subscription had no recorded state; an overlap means two
    states true at once. Either breaks point-in-time joins, which is the whole purpose of a
    type 2 dimension. Should return zero rows.
*/

with w as (
    select
        subscription_id,
        valid_from,
        valid_to,
        lead(valid_from) over (partition by subscription_id order by valid_from) as next_from
    from {{ ref('dim_subscription_history') }}
)

select subscription_id, valid_from, valid_to, next_from
from w
where next_from is not null
  and valid_to != next_from
