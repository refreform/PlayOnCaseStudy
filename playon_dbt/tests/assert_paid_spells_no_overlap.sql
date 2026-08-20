/*
    The merge in fct_user_paid_spells must produce spells that do NOT overlap each other.
    If two spells for the same user overlap, the gaps-and-islands logic failed -- most likely
    the nested-window case the model's comment warns about -- and any downstream "was the user
    paying on date X" answer would double-count.

    This is the test the model exists to be trusted by. It should return zero rows.
*/

select
    a.user_id,
    a.spell_number  as spell_a,
    b.spell_number  as spell_b,
    a.paid_from     as a_from,
    a.paid_to       as a_to,
    b.paid_from     as b_from,
    b.paid_to       as b_to
from {{ ref('fct_user_paid_spells') }} a
join {{ ref('fct_user_paid_spells') }} b
  on a.user_id = b.user_id
 and a.spell_number < b.spell_number
 and a.paid_from < b.paid_to
 and b.paid_from < a.paid_to
