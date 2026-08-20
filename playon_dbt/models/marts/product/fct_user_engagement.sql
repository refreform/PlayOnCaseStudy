/*
    Grain: ONE ROW PER REGISTERED USER. 8,000 rows.

    PRODUCT-OWNED. Carries the Product team's engagement definition, so it sits on the product side
    of the ownership boundary. Reads factual session measures from `data/fct_session` and the
    classification from `product/fct_session_engagement`.

    The headline table, and the one the business question is actually about: "how does
    viewership behaviour relate to subscription retention?" -- a question about people, not
    about sessions.

    WHY USER GRAIN AND NOT SESSION GRAIN. A session-grain fact answers "what do sessions look
    like"; aggregating it weights heavy viewers by how often they showed up. A user-grain fact
    answers "what do users look like", which is what retention means. In this dataset the
    distinction is nearly moot -- the median user has one session -- but that is an accident of
    synthetic data. On real data the two diverge sharply, and the grain of the fact silently
    decides which question gets answered. Session detail lives in `fct_session` for drill-down.

    SPINE IS ALL 8,000 USERS, not just those who watched. Users who never watched are the most
    unengaged cohort there is, and dropping them would bias every engagement-vs-retention
    comparison toward people who already showed up. Their engagement measures are zero, not
    null -- zero sessions is a measurement, not a gap.

    ANONYMOUS VIEWING IS NECESSARILY EXCLUDED. 929 sessions have no `user_id` (pre-sign-in
    viewing) and so cannot be attributed to anyone. They are retained in `fct_session`. This is
    a real limitation of the user grain, not a modelling error: the data does not say who those
    people were. Reconciliation between the two tables must account for it.

    NO FAN-OUT BY CONSTRUCTION. Every input is pre-aggregated to user grain before joining, so
    a user with several sessions or several subscriptions cannot multiply their own row.
    Asserted by `assert_fct_user_engagement_grain`.
*/

with users as (

    select * from {{ ref('dim_user') }}

),

sessions as (

    -- Factual session measures (Data) joined to our classification (Product). One row per
    -- session on both sides, so this join cannot fan out.
    select
        d.session_id,
        d.user_id,
        d.asset_id,
        d.sport,
        d.watch_minutes,
        d.session_start_at_utc,
        d.session_end_at_utc,
        d.completion_pct,
        e.is_engaged_view
    from {{ ref('fct_session') }} d
    join {{ ref('fct_session_engagement') }} e on d.session_id = e.session_id

),

engagement as (

    select
        user_id,
        count(*)                                                as session_count,
        count(*) filter (where is_engaged_view)                 as engaged_session_count,
        count(distinct asset_id)                                as distinct_assets_watched,

        sum(watch_minutes)                                      as total_watch_minutes,
        sum(case when is_engaged_view then watch_minutes else 0 end)
                                                                as engaged_watch_minutes,

        max(completion_pct)                                     as best_completion_pct,
        avg(completion_pct)                                     as avg_completion_pct,

        min(session_start_at_utc)                               as first_session_at,
        max(session_end_at_utc)                                 as last_session_at,

        count(distinct cast(session_start_at_utc as date))      as active_days,
        count(distinct sport)                                   as distinct_sports_watched

    from sessions
    where user_id is not null   -- anonymous sessions cannot be attributed; see header
    group by user_id

)

select
    u.user_id,

    -- ---------------------------------------------------------------- user attributes
    u.signup_date,
    u.home_state,
    u.acquisition_channel,

    -- ---------------------------------------------------------------- engagement measures
    coalesce(e.session_count, 0)                                as session_count,
    coalesce(e.engaged_session_count, 0)                        as engaged_session_count,
    coalesce(e.distinct_assets_watched, 0)                      as distinct_assets_watched,
    coalesce(e.distinct_sports_watched, 0)                      as distinct_sports_watched,
    coalesce(e.total_watch_minutes, 0)                          as total_watch_minutes,
    coalesce(e.engaged_watch_minutes, 0)                        as engaged_watch_minutes,
    coalesce(e.active_days, 0)                                  as active_days,
    e.best_completion_pct,
    e.avg_completion_pct,
    e.first_session_at,
    e.last_session_at,

    /*
        THE USER-LEVEL DEFINITION. An engaged user is one with at least one engaged view --
        a session in which they watched >= var('engaged_view_min_completion_pct') of the asset.

        "At least one" rather than "a majority of sessions" because the median user has exactly
        one session (p75 = 2, max 5): a ratio-based rule would be computed over a denominator of
        1 for most of the population and would say nothing a boolean does not. On real data,
        with real session counts, revisit this -- `engaged_session_count` and `session_count`
        are both exposed precisely so a different rule can be applied without remodelling.
    */
    coalesce(e.engaged_session_count, 0) > 0                    as is_engaged_user,

    -- Secondary tiering, for growth handoff. NOT the published definition -- see
    -- dev_docs/domain/engaged-view.md 6.4.
    case
        when coalesce(e.session_count, 0) = 0            then 'never_watched'
        when coalesce(e.engaged_session_count, 0) > 0    then 'engaged'
        when e.best_completion_pct
             >= {{ var('engaged_view_sampled_min_completion_pct') }}
                                                         then 'sampled'
        else                                                  'abandoned'
    end                                                         as engagement_tier,

    -- ---------------------------------------------------------------- retention measures
    u.has_subscription,
    u.subscription_count,
    u.latest_change_plan_type,
    u.latest_change_status,
    u.has_ever_paid,
    u.has_ever_churned,
    u.is_currently_subscribed,
    u.current_usd_mrr,
    u.paid_spell_count,
    u.total_paid_days,
    u.first_paid_at,

    /*
        Churn flag, stated narrowly on purpose. This says the user has ended every paid spell
        they held -- it does NOT say engagement preceded that ending. A causal reading needs a
        time-ordered cohort test (engagement in window W vs retention at W+30), which this
        table supports but does not itself perform. The measured result and its caveats:
        dev_docs/domain/engaged-view.md section 5.9.
    */
    u.has_ever_paid and not u.is_currently_subscribed           as has_churned_from_paid

from users u
left join engagement e on u.user_id = e.user_id
