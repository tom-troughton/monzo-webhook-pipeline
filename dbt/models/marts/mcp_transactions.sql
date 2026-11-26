-- The serving dataset for the MCP server's transaction-level tools (get_transactions,
-- search_transactions, get_spend_summary) - and the only thing those tools read (spec R9).
-- Exactly the row-shape columns from the spec, nothing else: raw account ids, counterparty bank
-- details and unsanitised text are not reachable from the server because they are not in here.
--
-- One Parquet file, not partitioned: ~5,000 rows is well under 1 MB, and on this storage every
-- extra file costs a ~140 ms HTTPS round-trip (one file ~1.3 s including the handshake), so a
-- single file is the fast layout for a reader that scans the whole table anyway.
--
-- Sign convention matches fct_transactions: amount_gbp is negative for spend, positive for
-- income/refunds.
{{ config(materialized='external', location=blob_location('marts', 'mcp_transactions.parquet')) }}

select
    t.transaction_id,
    t.created_at,
    (t.amount_minor_units / 100)::decimal(18, 2) as amount_gbp,
    (t.local_amount_minor_units / pow(10, coalesce(e.exponent, 2)))::decimal(18, 3) as local_amount,
    coalesce(t.local_currency, t.currency) as local_currency,
    {{ sanitise_text('t.merchant_name') }} as merchant_name,
    {{ sanitise_text('g.merchant_group_name') }} as merchant_group,
    t.merchant_country,
    t.merchant_city,
    t.merchant_online as is_online,
    t.category,
    -- A label, not an identifier: Monzo account ids aren't bank details, but nothing downstream
    -- needs more than "which of my accounts".
    'account ...' || right(t.account_id, 4) as account,
    {{ mask_counterparty('t.counterparty_name') }} as counterparty,
    t.is_declined,
    {{ sanitise_text('t.notes') }} as notes
from {{ ref('stg_transactions') }} t
left join {{ ref('currency_exponents') }} e
    on e.currency = coalesce(t.local_currency, t.currency)
left join {{ ref('int_merchant_groups') }} g
    on g.merchant_group_key = {{ merchant_group_key('t.merchant_group_id', 't.merchant_name', 't.merchant_id') }}
    and t.merchant_id is not null
