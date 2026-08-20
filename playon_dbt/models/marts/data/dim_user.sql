/*
    Grain: one row per registered account. 8,000 rows.

    The conformed user dimension. Attributes only -- no engagement or revenue measures, which
    live in `fct_user_engagement`. Keeping measures out of the dimension is what lets the
    Data team adopt this table without inheriting the Product team's definition of engagement.

    Subscription state IS included, because "what plan is this person on" is an attribute of the
    person, not a measure of them. It is expressed as flags and counts rather than an array of
    subscription ids: arrays are hostile to most BI tools, and this dimension is meant to be
    reusable beyond the Product team. Anyone needing the enumeration joins `dim_subscription_history`.
*/

with users as (

    select * from {{ ref('stg_users') }}

),

subscription_state as (

    /*
        One row per user. Aggregated BEFORE the join, so a user with several subscriptions
        cannot multiply their dimension row -- the fan-out the case study warns about.
    */
    select
        user_id,
        count(distinct subscription_id)                                     as subscription_count,
        min(valid_from)                                                     as first_subscription_at,

        /*
            arg_max, NOT max. An earlier version used
            `max(case when is_current_state then status end)`, which picks the alphabetically
            largest status among a user's current states rather than the most recent one. For
            the 268 users holding concurrent subscriptions that is simply wrong -- max('active',
            'canceled') is 'canceled' -- and it mislabelled 748 users as canceled, expired or
            trialing while they were in fact still subscribed.

            arg_max takes the status belonging to the most recently effective current state.
            Still a judgement for a user with two live subscriptions, but a defensible one
            rather than an alphabetical accident. For the boolean question, use
            is_currently_subscribed below, which is order-independent.

            Renamed too. "latest_status" reads as "this user's status", which it cannot be for
            anyone holding concurrent subscriptions -- 509 users have a most-recent change on a
            different subscription than their active one, and are correctly still subscribed.
            "latest_change_status" says what it actually is.
        */
        arg_max(plan_type, valid_from) filter (where is_current_state)       as latest_change_plan_type,
        arg_max(status,    valid_from) filter (where is_current_state)       as latest_change_status,

        bool_or(is_paid_plan)                                               as has_ever_paid,

        /*
            RESTRICTED TO PAID PLANS (WP-009). This previously read
            `bool_or(status in ('canceled','expired'))` across every row of a user's history,
            which counted a lapsed free trial as churn -- 564 trial rows reach `expired`
            without a cent ever being charged. A user who tried the product, did not convert
            and never paid has not churned; they never retained in the first place, and
            conflating the two inflates any churn figure with people who were never customers.

            `is_paid_plan` is plan_type in (monthly, annual), so this now reads: did a plan
            this user actually paid for end? Trial-only users are covered by has_ever_paid.
        */
        bool_or(is_paid_plan and status in ('canceled', 'expired'))         as has_ever_churned,

        /*
            The single "is this person subscribed right now" flag.

            Replaces a redundant pair: this and `has_open_paid_spell` (derived from the paid
            spells model) agreed on all 8,000 users, and could not disagree by construction --
            `status = 'active'` only ever occurs on a paid plan, never on a free trial. Two
            columns for one condition is two places to drift.

            Note what it excludes: a user on a free trial is NOT counted, because trialing is
            not paying. Their state is visible in `latest_change_status`.
        */
        bool_or(is_current_state and status = 'active')                     as is_currently_subscribed,
        sum(case when is_current_state and status = 'active'
                 then usd_monthly_amount else 0 end)                        as current_usd_mrr
    from {{ ref('dim_subscription_history') }}
    group by user_id

),

paid_tenure as (

    select
        user_id,
        count(*)                                                            as paid_spell_count,
        min(paid_from)                                                      as first_paid_at,
        sum(
            date_diff(
                'day',
                paid_from,
                -- the open-ended sentinel would produce a nonsense tenure; cap at the
                -- extract's last observed day instead of inventing a future one
                least(paid_to, (select max(valid_from) from {{ ref('dim_subscription_history') }}))
            )
        )                                                                   as total_paid_days
    from {{ ref('fct_user_paid_spells') }}
    group by user_id

)

select
    u.user_id,
    u.signup_at_utc,
    cast(u.signup_at_utc as date)                       as signup_date,
    u.home_state,
    u.acquisition_channel,

    coalesce(s.subscription_count, 0)                   as subscription_count,
    s.first_subscription_at,
    s.latest_change_plan_type,
    s.latest_change_status,
    coalesce(s.has_ever_paid, false)                    as has_ever_paid,
    coalesce(s.has_ever_churned, false)                 as has_ever_churned,
    coalesce(s.is_currently_subscribed, false)          as is_currently_subscribed,
    coalesce(s.current_usd_mrr, 0)                      as current_usd_mrr,

    coalesce(p.paid_spell_count, 0)                     as paid_spell_count,
    p.first_paid_at,
    coalesce(p.total_paid_days, 0)                      as total_paid_days,

    s.user_id is not null                               as has_subscription

from users u
left join subscription_state s on u.user_id = s.user_id
left join paid_tenure        p on u.user_id = p.user_id
