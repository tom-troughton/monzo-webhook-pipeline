select
    f.transaction_month,
    c.category,
    c.category_label,
    sum(-f.amount) as total_spend,
    count(*) as transaction_count
from {{ ref('fct_transactions') }} f
left join {{ ref('dim_category') }} c using (category)
where f.is_debit and not f.is_declined
group by f.transaction_month, c.category, c.category_label
order by f.transaction_month, total_spend desc
