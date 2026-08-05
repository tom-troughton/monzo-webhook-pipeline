-- Heuristic: a merchant charging the same amount in 2+ distinct calendar months looks recurring.
-- Good enough for a personal-finance mart; not a general subscription-detection algorithm.
{{ config(materialized='external', location=blob_location('marts', 'subscriptions.parquet')) }}

with recurring_charges as (
    select
        merchant_id,
        amount_minor_units,
        count(distinct transaction_month) as months_charged,
        count(*) as charge_count,
        min(created_at) as first_charged_at,
        max(created_at) as last_charged_at
    from {{ ref('fct_transactions') }}
    where is_debit and not is_declined and merchant_id is not null
    group by merchant_id, amount_minor_units
    having count(distinct transaction_month) >= 2
)

select
    r.merchant_id,
    m.merchant_name,
    m.merchant_category,
    -r.amount_minor_units / 100.0 as charge_amount,
    r.months_charged,
    r.charge_count,
    r.first_charged_at,
    r.last_charged_at
from recurring_charges r
left join {{ ref('dim_merchant') }} m using (merchant_id)
order by r.months_charged desc, charge_amount desc
