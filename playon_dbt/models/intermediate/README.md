# `models/intermediate/` — intentionally empty

This folder is empty on purpose, and that is a finding rather than an omission.

Genuinely intermediate models are **private plumbing**: models with no standalone meaning,
existing only because a mart query would otherwise be unreadable. Nobody outside the project
consumes them.

Four models lived here. Under review (WP-004) three turned out not to be plumbing at all —
`int_assets__resolved`, `int_subscriptions__windows` and `int_users__paid_spells` each had
standalone meaning to other teams, and were **promoted to `../marts/data/`**. The fourth,
`int_playback__sessions`, was doing two jobs at once and was **split**: the sessionization went
to `data/fct_session`, the engagement classification to `product/fct_session_engagement`.

The error worth remembering: leaving a shared asset in a private layer forces other teams
to re-derive it — the same slowly-changing-dimension windows, the same interval merge, the same
catalog resolution, each slightly differently. That re-derivation is exactly what a standardized
layer exists to prevent.

A four-source project simply does not generate much private glue. An empty layer is more honest
than a layer that hides publishable work.
