/*
    Grain: one row per registered account.

    The cleanest of the four extracts -- user_id is genuinely unique and both timestamp
    columns use a single encoding. The only work here is casting and standardizing
    home_state.
*/

with source as (

    select * from {{ source('raw', 'users') }}

),

cleaned as (

    select
        cast(user_id as bigint)                     as user_id,

        {{ normalize_timestamp('signup_ts') }}      as signup_at_utc,
        {{ timestamp_source_format('signup_ts') }}  as signup_ts_source_format,

        /*
            home_state arrives three ways: correct two-letter codes, lowercase two-letter
            codes (469 rows), and full names or punctuated abbreviations (32 rows).
            Uppercasing fixes the first problem; the handful of long forms are mapped
            explicitly. An explicit map is used rather than a fuzzy match because there are
            only four of them and a silent mismatch here would misattribute a user's region.
        */
        case upper(trim(home_state))
            when 'FLORIDA' then 'FL'
            when 'TEXAS'   then 'TX'
            when 'GEORGIA' then 'GA'
            when 'GA.'     then 'GA'
            else upper(trim(home_state))
        end                                         as home_state,

        home_state                                  as home_state_raw,
        acquisition_channel                         as acquisition_channel

    from source

)

select * from cleaned
