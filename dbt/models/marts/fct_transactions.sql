-- Grain: one row per transaction, including declined ones (a declined attempt is still a fact
-- worth keeping). Spend-based marts filter is_declined = false themselves.
select
    transaction_id,
    account_id,
    merchant_id,
    category,
    created_at,
    settled_at,
    date_trunc('month', created_at) as transaction_month,
    is_settled,
    is_declined,
    amount_minor_units,
    amount_minor_units / 100.0 as amount,
    amount_minor_units > 0 as is_credit,
    amount_minor_units < 0 as is_debit,
    currency,
    description,
    notes,
    ingestion_source
from {{ ref('stg_transactions') }}
