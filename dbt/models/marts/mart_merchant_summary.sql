{{ config(materialized='external', location=blob_location('marts', 'merchant_summary.parquet')) }}

select
    m.merchant_id,
    m.merchant_name,
    m.merchant_category,
    sum(-f.amount) as total_spend,
    count(*) as transaction_count,
    avg(-f.amount) as avg_transaction_amount,
    min(f.created_at) as first_transaction_at,
    max(f.created_at) as last_transaction_at
from {{ ref('fct_transactions') }} f
join {{ ref('dim_merchant') }} m using (merchant_id)
where f.is_debit and not f.is_declined
group by m.merchant_id, m.merchant_name, m.merchant_category
order by total_spend desc
