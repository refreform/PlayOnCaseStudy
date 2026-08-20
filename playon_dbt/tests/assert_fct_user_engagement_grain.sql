/*
    The fact table must be exactly one row per registered user, and must reconcile to the
    session model.

    Two failure modes this catches:
      1. Fan-out -- a user with several sessions or subscriptions multiplying their own row.
         This is the specific error the case study asks about, and pre-aggregating every input
         to user grain is what prevents it. This asserts the prevention worked.
      2. Silent session loss -- sessions present in fct_session but not counted in the fact.
         TWO legitimate differences exist and both are excluded from the comparison explicitly:
         anonymous sessions (no user_id at all), and 38 sessions whose user_id is absent from
         the users extract. The second was found BY this test -- those sessions looked
         attributable and disappeared at the join to dim_user. Any gap beyond those two means
         viewing vanished.

    Returns zero rows when healthy.
*/

with checks as (
    select
        (select count(*)                from {{ ref('fct_user_engagement') }})            as fact_rows,
        (select count(distinct user_id) from {{ ref('fct_user_engagement') }})            as fact_users,
        (select count(*)                from {{ ref('stg_users') }})                      as registered_users,
        (select sum(session_count)      from {{ ref('fct_user_engagement') }})            as sessions_in_fact,
        (select count(*) from {{ ref('fct_session') }}
          where user_id is not null and not has_unknown_user)                             as attributable_sessions
)

select *
from checks
where fact_rows      != registered_users     -- one row per user, no more, no less
   or fact_users     != registered_users     -- and user_id is genuinely unique
   or sessions_in_fact != attributable_sessions  -- no viewing lost or duplicated
