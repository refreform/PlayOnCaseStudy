/*
    Grain: one row per continuous period during which a user was a paying customer.

    WHY THIS EXISTS. A user can hold several subscriptions at once -- 319 overlapping pairs
    across 268 users involve two *paid* plans, not merely a trial overlapping its conversion.
    That makes "was this person paying on date X" ambiguous at subscription grain, and it breaks
    retention analysis in a specific way: a user who cancels one of two concurrent subscriptions
    looks churned when they are still paying. Counting subscription cancellations as churn
    would overstate it for exactly those 268 users.

    So paid windows are MERGED per user. A user paying Jan-Mar on one subscription and Feb-Jun
    on another has one continuous paid spell Jan-Jun, not two overlapping ones.

    THE ALGORITHM is a gaps-and-islands merge:
      1. Order each user's paid windows by start.
      2. A window starts a NEW spell if it begins after the latest end seen so far; otherwise it
         extends the current spell.
      3. Cumulative sum of the new-spell flag labels the spells; group and take min/max.

    The subtle part is step 2's running maximum. Using the PREVIOUS row's end is wrong when
    windows are nested -- a long window followed by a short one wholly inside it would be
    treated as a gap. `max(...) over (... rows between unbounded preceding and 1 preceding)`
    takes the furthest end seen so far, which handles nesting correctly. That case is tested in
    `tests/assert_paid_spells_no_overlap.sql`.

    BOUNDARY DECISION: windows that merely touch (one ends exactly when the next begins) are
    treated as CONTINUOUS, not as two spells. Strict inequality (`>` not `>=`) encodes that.
    For billing state this is right -- there is no instant where the user was unsubscribed.
*/

with paid_windows as (

    select
        user_id,
        subscription_id,
        valid_from,
        valid_to
    from {{ ref('dim_subscription_history') }}
    where is_paid_plan
      and is_active_state

),

ordered as (

    select
        *,
        max(valid_to) over (
            partition by user_id
            order by valid_from
            rows between unbounded preceding and 1 preceding
        ) as prior_furthest_end
    from paid_windows

),

flagged as (

    select
        *,
        case
            when prior_furthest_end is null then 1        -- first window for this user
            when valid_from > prior_furthest_end then 1   -- a genuine gap: new spell
            else 0                                        -- overlaps or touches: same spell
        end as starts_new_spell
    from ordered

),

islanded as (

    select
        *,
        sum(starts_new_spell) over (
            partition by user_id
            order by valid_from
            rows between unbounded preceding and current row
        ) as spell_number
    from flagged

)

select
    {{ dbt_utils.generate_surrogate_key(['user_id', 'spell_number']) }} as paid_spell_key,
    user_id,
    spell_number,
    min(valid_from)                     as paid_from,
    max(valid_to)                       as paid_to,
    count(*)                            as subscriptions_in_spell,
    count(distinct subscription_id)     as distinct_subscriptions,
    -- Compared against the same var dim_subscription_history mints it from.
    max(valid_to) = timestamp '{{ var('open_window_sentinel') }}' as is_open_ended
from islanded
group by user_id, spell_number
