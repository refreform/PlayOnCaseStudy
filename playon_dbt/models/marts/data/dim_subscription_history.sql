/*
    Grain: one row per subscription state, valid over a date range.
    A type 2 slowly changing dimension (SCD) built from the change log.

    We do NOT use dbt snapshots here. Snapshots exist to capture history from a source that
    overwrites itself; the billing extract already IS the history. Deriving windows from
    recorded change events is more honest than deriving them from when dbt happened to run --
    the validity dates reflect the business's timeline, not our scheduler's.

    So the whole construction is one window function: each change is valid until the next change
    to the same subscription. The final change is open-ended.

    ORPHANS FILTERED, consistent with fct_session: 118 rows referencing 74 user_ids
    absent from the users extract are dropped here. They remain intact in `stg_subscriptions`.

    MONTHLY NORMALIZATION HAPPENS HERE, replacing the per-period amounts (owner decision).
    Annual plans carry 79.99 -- a yearly price in a column the source named *monthly* recurring
    revenue. Staging refused to propagate the wrong name and exposed
    `billing_period_amount` + `billing_period_months`; this model divides through so that
    `monthly_amount` is genuinely comparable across plan types and summable.

    Free trials have billing_period_months = 0. Dividing by zero would be a silent infinity, so
    trials are set to 0.00 explicitly -- a trial's monthly recurring revenue is zero, which is
    both true and what a revenue sum should see.
*/

with changes as (

    select * from {{ ref('stg_subscriptions') }}

),

users as (

    select user_id from {{ ref('stg_users') }}

),

known_users_only as (

    -- The orphan filter. INNER JOIN on a unique key: cannot fan out.
    select c.*
    from changes c
    join users u on c.user_id = u.user_id

),

windowed as (

    select
        subscription_change_key,
        subscription_id,
        user_id,
        plan_type,
        status,
        currency,

        effective_at_utc                                        as valid_from,

        /*
            Valid until the next change to this subscription. The last change has no successor
            and stays open -- represented as a far-future sentinel rather than NULL so that
            BETWEEN and range-overlap predicates work without every consumer remembering to
            coalesce. The sentinel is deliberately absurd so it reads as "still open" rather
            than as a real date.

            The value is var('open_window_sentinel'), not a literal. fct_user_paid_spells
            compares against this exact value to derive is_open_ended, so the two must agree;
            as a literal in both files, changing one would have made every spell read as
            closed with no error and no failing test.
        */
        coalesce(
            lead(effective_at_utc) over (
                partition by subscription_id
                order by effective_at_utc
            ),
            timestamp '{{ var('open_window_sentinel') }}'
        )                                                       as valid_to,

        lead(effective_at_utc) over (
            partition by subscription_id order by effective_at_utc
        ) is null                                               as is_current_state,

        -- Normalized to a true monthly figure, in both native currency and USD.
        case
            when billing_period_months = 0 then 0.00
            else round(billing_period_amount / billing_period_months, 2)
        end                                                     as monthly_amount,
        case
            when billing_period_months = 0 then 0.00
            else round(usd_billing_period_amount / billing_period_months, 2)
        end                                                     as usd_monthly_amount,

        billing_period_months,

        -- Classification used by the paid-spell merge downstream.
        plan_type in ('monthly', 'annual')                      as is_paid_plan,
        status in ('active')                                    as is_active_state

    from known_users_only

)

select * from windowed
