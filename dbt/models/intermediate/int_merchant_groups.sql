-- One row per logical merchant (see the merchant_group_key() macro for how the key is chosen, and
-- why it's the normalised name rather than Monzo's group_id).
-- The display name is the most frequent merchant_name under the key, ties broken by most recent
-- use, so a group whose stores are named "UNIQLO 201" / "UNIQLO 34" / "Uniqlo" reads as whichever
-- spelling actually dominates the account's history.
with keyed as (

    select
        {{ merchant_group_key() }} as merchant_group_key,
        merchant_name,
        created_at
    from {{ ref('stg_transactions') }}
    where merchant_id is not null

),

names as (

    select
        merchant_group_key,
        merchant_name,
        count(*) as name_count,
        max(created_at) as name_last_used_at
    from keyed
    group by merchant_group_key, merchant_name

)

select
    merchant_group_key,
    coalesce(merchant_name, merchant_group_key) as merchant_group_name,
    sum(name_count) over (partition by merchant_group_key) as transaction_count
from names
qualify row_number() over (
    partition by merchant_group_key
    order by name_count desc, name_last_used_at desc, merchant_name
) = 1
