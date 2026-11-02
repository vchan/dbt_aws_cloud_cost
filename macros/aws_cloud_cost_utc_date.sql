{#-
    Calendar date of a timestamp, in UTC on both engines.

    BigQuery casts a TIMESTAMP to DATE in UTC. DuckDB uses the session time
    zone, which on a Lake Compute worker is not guaranteed to be UTC, so the
    date could shift by a day. `timezone('UTC', ...)` pins it.
-#}
{% macro aws_cloud_cost_utc_date(column) -%}
    {%- if var('aws_cloud_cost_reference', false) -%}
        cast({{ column }} as date)
    {%- else -%}
        cast(timezone('UTC', {{ column }}) as date)
    {%- endif -%}
{%- endmacro %}
