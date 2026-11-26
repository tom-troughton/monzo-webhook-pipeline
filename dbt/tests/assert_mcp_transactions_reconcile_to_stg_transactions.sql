-- Publication check for the MCP serving file, same reasoning as the other two published-artifact
-- tests (docs/decisions/0019): marts/mcp_transactions.parquet is what get_transactions,
-- search_transactions and get_spend_summary read, so assert on the file, not the model's SELECT.
-- depends_on: {{ ref('mcp_transactions') }}
--
-- Checks, each one row when it fails:
--   * every stg_transactions row was published, exactly once;
--   * the money adds up - sum(amount_gbp) equals the staging total in pence, exactly (decimal,
--     not double, so no tolerance needed);
--   * local_currency is always a three-letter ISO 4217-shaped code. A shape check rather than an
--     accepted_values list: Monzo can charge in any currency, and a full ISO list would be noise.

with published as (

    select * from read_parquet('{{ blob_location("marts", "mcp_transactions.parquet") }}')

),

modelled as (

    select
        count(*) as row_count,
        sum(amount_minor_units) as total_minor_units
    from {{ ref('stg_transactions') }}

),

published_totals as (

    select
        count(*) as row_count,
        count(distinct transaction_id) as distinct_ids,
        (sum(amount_gbp) * 100)::bigint as total_minor_units
    from published

)

select 'row_count_differs' as issue, p.row_count::varchar || ' published vs ' || m.row_count::varchar || ' modelled' as detail
from published_totals p, modelled m
where p.row_count != m.row_count

union all

select 'duplicate_transaction_ids', (p.row_count - p.distinct_ids)::varchar || ' duplicates'
from published_totals p
where p.row_count != p.distinct_ids

union all

select 'amount_total_differs', p.total_minor_units::varchar || ' published vs ' || m.total_minor_units::varchar || ' modelled (pence)'
from published_totals p, modelled m
where p.total_minor_units != m.total_minor_units

union all

select 'malformed_local_currency', transaction_id || ': ' || coalesce(local_currency, 'NULL')
from published
where not regexp_full_match(coalesce(local_currency, ''), '[A-Z]{3}')
