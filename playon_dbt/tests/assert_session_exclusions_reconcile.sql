/*
    Reconciliation: stg_playback_events -> fct_session.

    fct_session drops sessions on purpose (orphan asset_id, invalid asset runtime).
    This asserts the arithmetic exactly, so the exclusion can never drift silently -- if a
    future change drops one more session than the two documented reasons account for, this
    fails rather than quietly shrinking the analysis.

    Expected: 6,000 staged sessions -> 5,739 modelled, 261 excluded (123 orphan + 138 invalid).
*/

with counts as (
    select
        (select count(distinct session_id) from {{ ref('stg_playback_events') }}) as staged_sessions,
        (select count(*)                   from {{ ref('fct_session') }}) as modelled_sessions,
        (select count(*) from (
            select e.session_id
            from {{ ref('stg_playback_events') }} e
            left join {{ ref('dim_asset') }} a on e.asset_id = a.asset_id
            group by e.session_id
            having max(case when a.asset_id is null then 1 else 0 end) = 1
               or  max(case when a.duration_seconds is null then 1 else 0 end) = 1
        )) as expected_exclusions
)

select *, staged_sessions - modelled_sessions as actual_exclusions
from counts
where staged_sessions - modelled_sessions != expected_exclusions
