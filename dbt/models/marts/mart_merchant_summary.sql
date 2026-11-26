{{ config(materialized='external', location=blob_location('marts', 'merchant_summary.parquet')) }}

-- Grouped by logical merchant (int_merchant_groups), not merchant_id: Monzo gives each store or
-- payment route of one business its own merchant_id, so per-id grouping listed Amazon, TfL, Tesco
-- and others several times with split totals.
select
    g.merchant_group_key,
    g.merchant_group_name as merchant_name,
    mode(m.merchant_category) as merchant_category,
    sum(-f.amount) as total_spend,
    count(*) as transaction_count,
    avg(-f.amount) as avg_transaction_amount,
    min(f.created_at) as first_transaction_at,
    max(f.created_at) as last_transaction_at
from {{ ref('fct_transactions') }} f
join {{ ref('dim_merchant') }} m using (merchant_id)
join {{ ref('int_merchant_groups') }} g using (merchant_group_key)
where f.is_debit and not f.is_declined
group by g.merchant_group_key, g.merchant_group_name
order by total_spend desc
