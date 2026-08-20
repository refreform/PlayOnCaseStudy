/*
    Grain: one row per viewing session. 5,739 rows.

    PRODUCT-OWNED. This is the model that carries the Product team's opinion, and it is deliberately
    small: it takes the factual completion ratio from `data/fct_session` and applies a
    threshold to it. That is the entire contribution -- and it is the entire reason this sits on
    the product side of the ownership boundary.

    WHY THIS IS A SEPARATE MODEL. The engaged-view threshold is our definition, not a fact about
    PrepCast's data. If another team adopted `fct_session` they would get sessionization, watch
    minutes and completion ratios -- all things they would have had to build themselves and all
    things we agree on. What they would NOT get is our 30% cut, which they may reasonably
    disagree with. Isolating the opinion in one model means the Data layer stays adoptable
    and this model stays cheap to change.

    Test for which side a model belongs on: if the Product team's definition of engagement changed
    tomorrow, would this model change? Here, yes -- and nothing upstream of it would.

    The threshold itself is `var('engaged_view_min_completion_pct')`, declared in
    dbt_project.yml with no default. Full reasoning: dev_docs/domain/engaged-view.md section 6.
*/

with sessions as (

    select * from {{ ref('fct_session') }}

)

select
    session_id,
    user_id,
    asset_id,
    session_date,
    completion_pct,

    /*
        THE DEFINITION. An engaged view is a session in which the viewer watched at least
        30% of the asset's runtime.

        0.30 is the midpoint of an EMPTY band in the observed completion distribution
        (0.200 to 0.478). Every threshold in that band classifies all 5,739 sessions
        identically -- 1,826 engaged, 31.8% -- so nothing depends on the precise value. That
        insensitivity is also what makes this knob impossible to quietly tune toward a
        retention result.
    */
    completion_pct >= {{ var('engaged_view_min_completion_pct') }}   as is_engaged_view,

    /*
        Secondary three-tier split. NOT the published definition -- retained because the middle
        tier (watched 17-20%, then stopped) is a churn-reduction target worth handing to growth.
        The distribution genuinely has three clusters separated by two empty gaps; the
        engagement boundary is the wider of the two. See engaged-view.md section 6.4, and note
        section 5.9 -- these tiers show no retention signal in this dataset.
    */
    case
        when completion_pct < {{ var('engaged_view_sampled_min_completion_pct') }}
                                                                          then 'abandoned'
        when completion_pct < {{ var('engaged_view_min_completion_pct') }} then 'sampled'
        else                                                                   'engaged'
    end                                                              as engagement_tier

from sessions
