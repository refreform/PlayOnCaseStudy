/*
    Grain: one row per distinct video asset.

    KEY DECISION -- the source asset_id is not unique. Twelve ids appear twice, and each pair
    is a game plus its "(Replay)": identical schools, sport, scheduled start and duration,
    differing only in title and (for nine of the twelve) LIVE vs VOD. These are two real
    assets that were issued one id, not a corrupt duplicate to be deduplicated away.

    So this model mints a surrogate key over (asset_id, title, asset_type), which is unique
    across all 862 rows and gives the catalog a grain that is actually true. Both the natural
    key and the surrogate are exposed.

    The key hashes the TRIMMED title, matching the column this model exposes and the
    uniqueness test in _staging__models.yml. Hashing the raw title instead would mean the
    key, the exposed column and the test each operated on a slightly different value: two
    rows differing only in whitespace would produce two distinct keys while the test that is
    supposed to guard the key saw one. No effect on the current extract (trimming changes
    nothing -- 862 distinct either way), which is exactly why it is worth fixing now rather
    than after an extract where it does.

    WHAT THIS DOES NOT FIX: a playback event carries only asset_id, so events landing on one
    of those twelve ids still cannot be attributed to the live broadcast or to the replay.
    The surrogate key makes the *dimension* trustworthy; it does not recover information the
    fact table never had. That attribution decision belongs downstream, in `dim_asset`.
*/

with source as (

    select * from {{ source('raw', 'asset_catalog') }}

),

cleaned as (

    select
        {{ dbt_utils.generate_surrogate_key(['asset_id', 'trim(title)', 'asset_type']) }}
                                                        as asset_key,
        cast(asset_id as bigint)                        as asset_id,
        trim(title)                                     as title,
        asset_type                                      as asset_type,

        -- Identifies the second row of each colliding pair. The 12 duplicated asset_ids are a
        -- game and its "(Replay)", and the title suffix is the only field that distinguishes
        -- them -- so this is derived from the one signal the source actually gives us.
        trim(title) like '%(Replay)'                    as is_replay,

        /*
            24 raw sport variants collapse to 10. Uppercasing resolves every casing variant
            (Hockey/HOCKEY, football/FOOTBALL), leaving exactly three abbreviations to map by
            hand. Mapped explicitly rather than by pattern match: "VB" is only obviously
            volleyball to someone who already knows the answer.
        */
        case upper(trim(sport))
            when 'BBALL' then 'BASKETBALL'
            when 'VB'    then 'VOLLEYBALL'
            when 'FB'    then 'FOOTBALL'
            else upper(trim(sport))
        end                                             as sport,

        sport                                           as sport_raw,
        trim(home_school)                               as home_school,
        trim(away_school)                               as away_school,

        {{ normalize_timestamp('scheduled_start_ts') }}     as scheduled_start_at_utc,
        {{ timestamp_source_format('scheduled_start_ts') }} as scheduled_start_ts_source_format,

        /*
            20 assets carry impossible runtimes (five at -600, five at -1, ten at 0). Nulled rather than kept or
            defaulted: this column is the denominator of every completion metric, and a null
            propagates honestly to a null ratio, whereas a zero divides by zero and a
            substituted average invents a number nobody measured.

            The raw value is preserved alongside so the defect stays visible and countable.
        */
        case
            when cast(duration_seconds as double) < 1 then null
            else cast(duration_seconds as double)
        end                                             as duration_seconds,

        cast(duration_seconds as double)                as duration_seconds_raw,
        cast(duration_seconds as double) < 1            as has_invalid_duration

    from source

)

select * from cleaned
