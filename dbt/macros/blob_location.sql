{#
  Resolves an output location for external (Parquet-to-Blob) materializations.
  `azure` target writes to the real container; every other target writes to a local
  export/ folder instead, so `dbt build` never needs Azure auth just to build marts locally.
#}
{% macro blob_location(container, filename=none) %}
  {%- set base = ('az://' ~ container) if target.name == 'azure' else ('export/' ~ container) -%}
  {{ return(base ~ '/' ~ filename if filename else base) }}
{% endmacro %}
