/*
    Grain: one row per subscription status/plan change event.

    This is a change log, not a dimension. It stays at change-event grain here; collapsing it
    into validity windows (the slowly changing dimension work) happens in the intermediate
    layer, where the ordering and gap rules can be reasoned about in one place.

    Uniqueness is on (subscription_id, event_effective_ts), verified 8,014/8,014 distinct.
    A surrogate key over that pair is minted so downstream models have a single-column key.

    COLUMN RENAME -- the source calls this `mrr_amount`, but annual plans carry 79.99, which
    is a yearly price, not a monthly one. The name is simply wrong at source. Rather than
    propagate a misleading name into the cleaned layer, it is renamed to
    `billing_period_amount`: the amount charged per billing period, whatever that period is.
    `billing_period_months` carries the period length so `dim_subscription_history` can normalize
    to a true monthly figure when it needs one.

    Deliberately NOT normalized to monthly here. A per-period amount is the correct fact for
    non-product use cases (billing reconciliation, cash collected), and monthly-normalized
    revenue is a product-analytics view built on top. Staging keeps the source's true grain;
    the derivation belongs downstream.

    KNOWN ISSUES CARRIED THROUGH, NOT FIXED HERE:

      * 118 rows reference 74 user_ids absent from the users extract. Retained by design and
        filtered in `dim_subscription_history` -- see stg_playback_events for the reasoning.

      * 53 subscriptions show backward status transitions (canceled -> active, expired ->
        trialing). Most likely genuine win-backs, which is a retention success rather than a
        defect. Confirmation is an open question; no ordering assumption is made here beyond
        sorting by event_effective_ts.

      * A user may hold several subscriptions, including genuinely concurrent paid ones.
        Resolving "the user's plan on date X" is a decision for `dim_subscription_history`.
*/

with source as (

    select
        *,
        -- Cast once, here, so the amount and its currency-converted twin below cannot drift
        -- apart if one of them is later edited.
        cast(mrr_amount as double) as mrr_amount_typed,

        -- Normalized once, here, for the same reason. This value is read three times below --
        -- as the published column, by the source-format flag, and inside the fx join predicate
        -- -- and the join is the one that matters: if the predicate's normalization ever drifted
        -- from the column's, rows would silently match the wrong rate period and the row-count
        -- reconciliation would still pass.
        {{ normalize_timestamp('event_effective_ts') }}     as effective_at_utc_typed,
        {{ timestamp_source_format('event_effective_ts') }} as effective_ts_source_format_typed

    from {{ source('raw', 'subscriptions') }}

),

fx as (

    select * from {{ ref('fx_rates') }}

),

cleaned as (

    select
        {{ dbt_utils.generate_surrogate_key(['subscription_id', 'event_effective_ts']) }}
                                                         as subscription_change_key,
        cast(source.subscription_id as bigint)           as subscription_id,
        cast(source.user_id as bigint)                   as user_id,

        source.plan_type                                 as plan_type,
        source.status                                    as status,

        source.effective_at_utc_typed                    as effective_at_utc,
        source.effective_ts_source_format_typed          as effective_ts_source_format,

        -- Renamed from the source's `mrr_amount` -- see header. This is the charge per
        -- billing period, not per month.
        source.mrr_amount_typed                          as billing_period_amount,
        source.currency                                  as currency,

        /*
            Converted via the fx_rates seed rather than hardcoded constants, so a rate change
            is an append to a table finance owns and past periods keep reproducing the same
            number. The join is on the rate valid at the change's effective date.
        */
        round(source.mrr_amount_typed * fx.rate_to_usd, 2)
                                                        as usd_billing_period_amount,

        -- Months covered by one billing period. Lets dim_subscription_history derive a true
        -- monthly figure without re-deciding what "annual" means.
        case source.plan_type
            when 'monthly'    then 1
            when 'annual'     then 12
            when 'free_trial' then 0
        end                                             as billing_period_months

    from source
    /*
        LEFT JOIN, not INNER: an unmapped currency or an uncovered date must surface as a
        NULL that the not_null test catches, never as a silently dropped subscription row.
        Fan-out here is prevented by the uniqueness test on the seed, not by hope.
    */
    left join fx
        on source.currency = fx.currency
       and cast(source.effective_at_utc_typed as date)
           between fx.valid_from and fx.valid_to

)

select * from cleaned
