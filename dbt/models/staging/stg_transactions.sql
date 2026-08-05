{{
    config(
        materialized='incremental',
        unique_key='transaction_id',
        incremental_strategy='merge'
    )
}}

-- Reconciliation is the source of truth over webhook deliveries (docs/decisions/0001), so
-- when the same transaction_id somehow shows up more than once in a run, reconciliation wins.
with source as (

    select * from {{ source('raw', 'transactions') }}

),

renamed as (

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
    from source

)

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
from renamed
where row_num = 1

{% if is_incremental() %}
    and created_at > (select coalesce(max(created_at), '1900-01-01'::timestamp) from {{ this }})
{% endif %}
