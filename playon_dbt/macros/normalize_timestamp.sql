{#
    Normalize the three timestamp encodings found in the raw extracts to a single naive
    TIMESTAMP holding UTC.

    The raw data mixes:
      1. Unix epoch seconds          e.g. 1756693468        (19.7% of playback_events)
      2. ISO-8601 with a Z suffix    e.g. 2025-09-01T00:35:18Z
      3. ISO-8601, space-separated, NO timezone marker
                                     e.g. 2025-09-01 17:41:06

    Form 3 is the dangerous one: it carries no timezone at all, so treating it as UTC is an
    ASSUMPTION, not a reading of the data. The owner made that call deliberately and it is an
    open question for the source team -- see dev_docs/project/open-questions.md. If the answer
    comes back "those are US/Eastern", every value produced by branch 3 moves by 4-5 hours and
    this macro is the single place that changes.

    Output is a naive TIMESTAMP (not TIMESTAMPTZ) deliberately. TIMESTAMPTZ renders in the
    reader's session timezone, so a value would display differently for different analysts and
    silently shift a date-grain aggregate across a day boundary. A naive TIMESTAMP that we
    guarantee is UTC is boring and portable, which is what a warehouse column should be.

    Verified 2026-08-18: 0 parse failures across all 216,045 playback_events rows and all
    8,014 subscriptions rows.
#}

{% macro normalize_timestamp(column_name) %}
    case
        -- 1. all digits -> Unix epoch seconds
        when regexp_matches({{ column_name }}, '^[0-9]+$')
            then to_timestamp(try_cast({{ column_name }} as bigint)) at time zone 'UTC'
        -- 2. ISO-8601 with explicit Z -> already UTC, strip the marker and cast
        when {{ column_name }} like '%T%Z'
            then try_cast(
                replace(replace({{ column_name }}, 'T', ' '), 'Z', '') as timestamp
            )
        -- 3. no timezone marker -> ASSUMED UTC (see macro header)
        else try_cast({{ column_name }} as timestamp)
    end
{% endmacro %}


{#
    Flag which encoding a raw timestamp arrived in, so the assumption in branch 3 stays
    visible and auditable downstream rather than disappearing into a clean column.
#}
{% macro timestamp_source_format(column_name) %}
    case
        when regexp_matches({{ column_name }}, '^[0-9]+$') then 'epoch_seconds'
        when {{ column_name }} like '%T%Z'                 then 'iso8601_utc'
        else 'iso8601_no_timezone_assumed_utc'
    end
{% endmacro %}
