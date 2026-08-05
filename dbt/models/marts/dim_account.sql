-- Degenerate dimension: the raw transaction feed is the only source of account data we have
-- (no separate Monzo /accounts ingestion yet), so this is derived from transaction activity.
select
    account_id,
    min(created_at) as first_transaction_at,
    max(created_at) as last_transaction_at,
    count(*) as transaction_count
from {{ ref('stg_transactions') }}
group by account_id
