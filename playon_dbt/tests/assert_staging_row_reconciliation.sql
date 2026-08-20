/*
    Row-count reconciliation for the three staging models that must not change row counts at
    all. (playback_events has its own test, because it alone drops rows by design -- see
    assert_playback_events_row_reconciliation.sql.)

    Expected: exact equality. asset_catalog 862, users 8,000, subscriptions 8,014.

    This is not busywork on a model with no WHERE clause. stg_subscriptions left-joins the
    fx_rates seed on a currency and a date range, and a join is the classic way a staging
    model silently gains rows: two seed rows covering one currency on overlapping dates would
    duplicate every subscription change in that currency, and every other test in the project
    would still pass. The seed's own uniqueness test guards the cause; this guards the
    symptom, which is the one that shows up in a revenue number.

    Fails with a row per model whose arithmetic does not hold.
*/

with reconciliation as (

    select
        'stg_asset_catalog'                                          as model_name,
        (select count(*) from {{ source('raw', 'asset_catalog') }})   as raw_rows,
        (select count(*) from {{ ref('stg_asset_catalog') }})         as staged_rows

    union all

    select
        'stg_users',
        (select count(*) from {{ source('raw', 'users') }}),
        (select count(*) from {{ ref('stg_users') }})

    union all

    select
        'stg_subscriptions',
        (select count(*) from {{ source('raw', 'subscriptions') }}),
        (select count(*) from {{ ref('stg_subscriptions') }})

)

select
    model_name,
    raw_rows,
    staged_rows,
    staged_rows - raw_rows as row_delta
from reconciliation
where raw_rows != staged_rows
