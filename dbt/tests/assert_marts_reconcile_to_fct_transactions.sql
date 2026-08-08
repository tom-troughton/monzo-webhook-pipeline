-- Aggregation check: the published marts add back up to the fact table they were derived from.
-- The spec's Data Quality section asks for sum reconciliation between layers; this is the
-- warehouse-internal half of it (raw/-to-model completeness is covered by
-- assert_raw_blobs_reconcile_to_stg_transactions.sql).
--
-- Every mart applies its own filters (is_debit, not is_declined, merchant_id is not null), so the
-- expected total is restated here from fct_transactions under the same predicate. That duplication
-- is the test: a filter silently changing in a mart - a `not is_declined` dropped, an inner join
-- to a dim quietly excluding rows - moves the published total away from the fact table, which is
-- invisible to every column-level test on the mart itself.
--
-- Reads the published Parquet rather than ref()-ing the mart models, for the same reason as
-- assert_staging_export_matches_stg_transactions.sql: these files are what mcp_server and
-- scripts/query_marts.py actually query, so the artifact is the thing worth asserting on. The refs
-- below only order this test after the writes.
-- depends_on: {{ ref('mart_monthly_cashflow') }}
-- depends_on: {{ ref('mart_spend_by_category') }}
-- depends_on: {{ ref('mart_merchant_summary') }}
--
-- Money columns are DOUBLE (amount_minor_units / 100.0), so equality is compared to within half a
-- penny rather than exactly - summing the same values in a different grouping order is free to
-- differ in the last bits. Counts are integers and compared exactly.

with fct as (

    select
        sum(amount) filter (where not is_declined) as net_total,
        sum(-amount) filter (where is_debit and not is_declined) as debit_total,
        count(*) filter (where is_debit and not is_declined) as debit_count,
        sum(-amount) filter (where is_debit and not is_declined and merchant_id is not null) as merchant_debit_total
    from {{ ref('fct_transactions') }}

),

cashflow as (

    select
        sum(net) as net_total,
        sum(income) - sum(expenses) as net_from_components
    from read_parquet('{{ blob_location("marts", "monthly_cashflow.parquet") }}')

),

by_category as (

    select
        sum(total_spend) as debit_total,
        sum(transaction_count) as debit_count
    from read_parquet('{{ blob_location("marts", "spend_by_category.parquet") }}')

),

by_merchant as (

    select sum(total_spend) as merchant_debit_total
    from read_parquet('{{ blob_location("marts", "merchant_summary.parquet") }}')

),

checks as (

    select
        'monthly_cashflow.net vs fct_transactions.amount' as check_name,
        cashflow.net_total as published_value,
        fct.net_total as expected_value
    from cashflow cross join fct

    union all

    -- Internal consistency: the mart's own income/expenses split must agree with its own net.
    select
        'monthly_cashflow income - expenses vs net',
        cashflow.net_from_components,
        cashflow.net_total
    from cashflow

    union all

    select
        'spend_by_category.total_spend vs fct_transactions debit spend',
        by_category.debit_total,
        fct.debit_total
    from by_category cross join fct

    union all

    select
        'spend_by_category.transaction_count vs fct_transactions debit count',
        by_category.debit_count,
        fct.debit_count
    from by_category cross join fct

    union all

    select
        'merchant_summary.total_spend vs fct_transactions merchant debit spend',
        by_merchant.merchant_debit_total,
        fct.merchant_debit_total
    from by_merchant cross join fct

)

select
    check_name,
    published_value,
    expected_value,
    published_value - expected_value as difference
from checks
where abs(coalesce(published_value, 0) - coalesce(expected_value, 0)) > 0.005
