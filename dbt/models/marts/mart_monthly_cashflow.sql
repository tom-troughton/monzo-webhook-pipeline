{{ config(materialized='external', location=blob_location('marts', 'monthly_cashflow.parquet')) }}

select
    transaction_month,
    sum(case when is_credit then amount else 0 end) as income,
    sum(case when is_debit then -amount else 0 end) as expenses,
    sum(amount) as net
from {{ ref('fct_transactions') }}
where not is_declined
group by transaction_month
order by transaction_month
