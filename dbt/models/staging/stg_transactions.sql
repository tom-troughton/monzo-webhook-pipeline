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
-- union until staging/ has been rewritten with the new shape - union_by_name only reconciles
-- columns that exist in at least one file being read, so a brand-new column binds against
-- nothing and errors. Any column change here needs a one-off `dbt build --target azure
-- --full-refresh` (which skips the union entirely - see incremental_scan_from()) to republish
-- staging/, after which normal incremental runs work again.
--
-- Reconciliation is the source of truth over webhook deliveries (docs/decisions/0001) - within a
-- single raw/ read that only matters if the same transaction_id somehow appears twice (shouldn't
-- happen given raw/'s one-blob-per-id naming, kept as a defensive tie-break). Between the new
-- read and the existing staging/ output, the new read always wins for any overlapping
-- transaction_id, since it reflects raw/'s current state and the existing row is a stale copy
-- from a prior run - that's the whole point of re-scanning the overlap window.

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
    from read_parquet('{{ blob_location("staging") }}/**/*.parquet', union_by_name=true)
    where transaction_id not in (select transaction_id from new_deduped)

)

select * from new_deduped
union all
select * from existing
{% else %}
select * from new_deduped
{% endif %}
