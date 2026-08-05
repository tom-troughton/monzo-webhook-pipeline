select
    merchant_id,
    any_value(merchant_name) as merchant_name,
    any_value(merchant_category) as merchant_category,
    any_value(merchant_emoji) as merchant_emoji,
    any_value(merchant_online) as is_online_merchant,
    any_value(merchant_atm) as is_atm
from {{ ref('stg_transactions') }}
where merchant_id is not null
group by merchant_id
