{#
  Untrusted-text handling for anything the MCP server returns (spec R4). Notes, merchant names and
  counterparty names are user- or third-party-supplied - a payment reference is attacker-
  controllable - so they reach an LLM client only after control characters are stripped,
  whitespace collapsed and length capped. Done here, in the model, rather than in Python, so the
  published Parquet itself never holds the raw form.
#}
{% macro sanitise_text(expr, max_length=140) %}
    nullif(left(trim(regexp_replace(regexp_replace({{ expr }}, '[[:cntrl:]]', ' ', 'g'), '\s+', ' ', 'g')), {{ max_length }}), '')
{% endmacro %}

{#
  Counterparty minimisation (spec R5): "Jane Doe" -> "Jane D.", a single word stays as it is.
  Monzo's counterparty object also carries sort code / account number, but the source schema in
  _sources.yml never reads those fields at all.
#}
{% macro mask_counterparty(expr) %}
    case
        when {{ expr }} is null then null
        when len(string_split(trim({{ expr }}), ' ')) = 1 then {{ sanitise_text(expr, 60) }}
        else {{ sanitise_text("string_split(trim(" ~ expr ~ "), ' ')[1]", 40) }}
            || ' '
            || upper(left(string_split(trim({{ expr }}), ' ')[-1], 1))
            || '.'
    end
{% endmacro %}

{#
  Fallback merchant grouping key when Monzo gives no group_id: lower-case, store numbers and
  trailing "#12" / "No. 4" style suffixes removed, so "UNIQLO 201" and "Uniqlo" collapse together.
#}
{% macro normalised_merchant_name(expr) %}
    nullif(trim(regexp_replace(regexp_replace(lower({{ expr }}), '\s*(#|no\.?\s*)?[0-9]+\s*$', ''), '\s+', ' ', 'g')), '')
{% endmacro %}

{#
  The logical-merchant key: the normalised merchant name, falling back to Monzo's group_id and then
  the merchant_id when there is no name.

  Name first, not group_id, because of what group_id turned out to be in real data (checked
  2026-11-26 across every raw/ blob: 1,256 merchant_ids, 775 group_ids, no group with more than one
  spelling): Monzo assigns one group per merchant *spelling*. It does fold the many merchant_ids
  behind one spelling together (51 for "Amazon", 34 for "Tesco" - the duplicates get_top_merchants
  showed), but "UNIQLO 201", "UNIQLO 202" and "Uniqlo" are separate groups. Every real row has a
  group_id, so as a primary key the name fallback would never run. The normalised name is never
  finer than group_id and also folds the store-numbered spellings.
#}
{% macro merchant_group_key(group_id='merchant_group_id', name='merchant_name', id='merchant_id') %}
    coalesce('name:' || {{ normalised_merchant_name(name) }}, {{ group_id }}, {{ id }})
{% endmacro %}
