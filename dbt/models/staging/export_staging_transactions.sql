-- Publishes stg_transactions to staging/ as Hive-partitioned Parquet. Kept separate from
-- stg_transactions itself because dbt-duckdb's `external` materialization always does a full
-- rewrite - it can't also be `incremental`/merge, which stg_transactions needs to dedupe
-- webhook vs. reconciliation sources without rescanning all of raw/ every run.
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

select
    *,
    strftime(created_at, '%Y') as transaction_year,
    strftime(created_at, '%m') as transaction_month
from {{ ref('stg_transactions') }}
