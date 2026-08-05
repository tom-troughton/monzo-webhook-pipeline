-- Publishes stg_transactions to staging/ as Hive-partitioned Parquet. Kept separate from
-- stg_transactions itself because dbt-duckdb's `external` materialization always does a full
-- rewrite of whatever its SELECT returns - it can't also be `incremental`/merge, which
-- stg_transactions needs to dedupe webhook vs. reconciliation sources.
--
-- "Full rewrite" is per-run, not per-partition though: DuckDB's partitioned COPY only touches
-- partitions actually present in the result set (confirmed empirically - overwrite_or_ignore
-- updates an existing partition's content correctly, but leaves partitions absent from this run's
-- result set alone, doesn't delete them). So scoping the SELECT to incremental_scan_from()'s
-- window here has the same effect as scoped_raw_transactions_source() does for the read side:
-- only the months that could plausibly have changed get rewritten, not all of them every run.
{{
    config(
        materialized='external',
        location=blob_location('staging'),
        options={
            'format': 'parquet',
            'partition_by': 'transaction_year, transaction_month',
            'overwrite_or_ignore': 'true'
        }
    )
}}

{%- set scan_from = incremental_scan_from() -%}

select
    *,
    strftime(created_at, '%Y') as transaction_year,
    strftime(created_at, '%m') as transaction_month
from {{ ref('stg_transactions') }}
{%- if scan_from is not none %}
where created_at >= '{{ scan_from.isoformat() }}'
{%- endif %}
