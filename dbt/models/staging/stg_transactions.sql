{{ config(materialized='table') }}

-- Deliberately NOT dbt's `incremental` materialization - see dbt/macros/incremental_scoping.sql
-- for why (GitHub Actions runners are ephemeral, so a version gated on is_incremental() silently
-- never activated in CI - every run fell through to a full unscoped raw/ scan regardless).
-- Instead this is rebuilt fresh every run by unioning a scoped raw/ read with the already-
-- published staging/ output: correctness doesn't depend on any local state surviving between
-- runs, since "old" data comes from durable Blob Storage and only "new" data comes from raw/.
--
-- Gotcha when editing this model: the `existing` CTE below selects explicit column names out of
-- staging/'s already-published Parquet. Adding or renaming a column above therefore breaks the
-- union until staging/ has been rewritten with the new shape, since a brand-new column binds
-- against nothing in the already-published files and errors. Any column change here needs a
-- one-off `dbt build --target azure --full-refresh` (which skips the union entirely - see
-- incremental_scan_from()) to republish staging/, after which normal incremental runs work again.
--
-- Reconciliation is the source of truth over webhook deliveries (docs/decisions/0001) - within a
-- single raw/ read that only matters if the same transaction_id somehow appears twice (shouldn't
-- happen given raw/'s one-blob-per-id naming, kept as a defensive tie-break). The two branches of
-- the union can't overlap at all: `new_deduped` covers whole months from the watermark forward and
-- `existing` is filtered to months strictly before it, which is only sound because raw/ is pathed
-- by created_at month exactly as staging/ is partitioned by it (functions/shared/blob_writer.py
-- writes raw/%Y/%m/%d/<id>.json). Those two layouts have to stay in step - see
-- docs/decisions/0018-partition-aligned-incremental-window.md.

{% set scan_from = incremental_scan_from() %}

with new_read as (

    select
        transaction.id as transaction_id,
        transaction.account_id as account_id,
        transaction.amount as amount_minor_units,
        transaction.currency as currency,
        transaction.created::timestamp as created_at,
        -- Monzo sends settled as "" (not null) for unsettled/pending transactions.
        nullif(transaction.settled, '')::timestamp as settled_at,
        transaction.description as description,
        transaction.category as category,
        nullif(transaction.notes, '') as notes,
        transaction.is_load as is_load,
        transaction.decline_reason as decline_reason,
        transaction.merchant.id as merchant_id,
        transaction.merchant.name as merchant_name,
        transaction.merchant.category as merchant_category,
        transaction.merchant.emoji as merchant_emoji,
        transaction.merchant.online as merchant_online,
        transaction.merchant.atm as merchant_atm,
        source as ingestion_source,
        row_number() over (
            partition by transaction.id
            order by (source = 'reconciliation') desc
        ) as row_num
    from {{ scoped_raw_transactions_source(scan_from) }}

),

new_deduped as (

    select
        transaction_id,
        account_id,
        amount_minor_units,
        currency,
        created_at,
        settled_at,
        settled_at is not null as is_settled,
        decline_reason is not null as is_declined,
        description,
        category,
        notes,
        is_load,
        decline_reason,
        merchant_id,
        merchant_name,
        merchant_category,
        merchant_emoji,
        merchant_online,
        merchant_atm,
        ingestion_source
    from new_read
    where row_num = 1

)

{% if scan_from is not none %}
,

existing as (

    select
        transaction_id,
        account_id,
        amount_minor_units,
        currency,
        created_at,
        settled_at,
        is_settled,
        is_declined,
        description,
        category,
        notes,
        is_load,
        decline_reason,
        merchant_id,
        merchant_name,
        merchant_category,
        merchant_emoji,
        merchant_online,
        merchant_atm,
        ingestion_source
    -- Partition predicate, not an anti-join against new_deduped. The two are equivalent here
    -- (verified: both return the same row count and the same distinct transaction_id count),
    -- because raw/ is pathed by created_at month exactly like staging/ is partitioned by it - so
    -- every staging row in a scanned month is by definition re-read from raw/ above. Preferred
    -- for two reasons: `not in` against a subquery is a NULL trap (one malformed raw blob yields
    -- a NULL transaction_id, the predicate goes UNKNOWN for every row, and this CTE silently
    -- returns nothing - collapsing history to just the scan window), and this form lets DuckDB
    -- prune whole partitions at planning time.
    --
    -- transaction_year comes back as BIGINT but transaction_month as VARCHAR ('07' keeps its
    -- leading zero, so Hive type autocast leaves it alone) - hence explicit ::int on both rather
    -- than string concatenation, which would depend on that inference staying put.
    from read_parquet('{{ blob_location("staging") }}/**/*.parquet', hive_partitioning=true)
    where transaction_year::int * 100 + transaction_month::int < {{ scan_from.strftime('%Y%m') | int }}

)

-- `by name`, not positional: the two branches list 20 columns of which description/category/notes
-- are all VARCHAR and is_settled/is_declined/is_load/merchant_online/merchant_atm are all BOOLEAN,
-- so a positional union would silently swap values if either list were ever reordered.
select * from new_deduped
union all by name
select * from existing
{% else %}
select * from new_deduped
{% endif %}
