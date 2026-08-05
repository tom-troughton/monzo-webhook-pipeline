select distinct
    category,
    upper(substr(replace(category, '_', ' '), 1, 1)) || substr(replace(category, '_', ' '), 2) as category_label
from {{ ref('stg_transactions') }}
where category is not null
