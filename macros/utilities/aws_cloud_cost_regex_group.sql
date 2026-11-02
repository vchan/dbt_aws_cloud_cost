{#- First capture group of `pattern` in `expression`.
    BigQuery's regexp_extract returns the first capture group on its own and
    takes no group index, so `group_index` must be 1 there. -#}
{% macro aws_cloud_cost_regex_group(expression, pattern, group_index) -%}
    {%- if target.type == 'bigquery' -%}
        regexp_extract({{ expression }}, '{{ pattern }}')
    {%- else -%}
        regexp_extract({{ expression }}, '{{ pattern }}', {{ group_index }})
    {%- endif -%}
{%- endmacro %}
