{#
  Scopes stg_transactions' raw/ read to a recent date window instead of scanning every file in
  raw/ on every run - the naive full glob became an ~8 minute (and growing) bottleneck once raw/
  held years of individual per-transaction JSON files (one blob per transaction, by design - see
  functions/shared/blob_writer.py).

  The watermark comes from staging/'s already-published Parquet (durable, in Blob Storage), not
  the local incremental table ({{ this }}). GitHub Actions runners are ephemeral, so the local
  DuckDB catalog doesn't exist yet when CI's `publish` job starts - reading the watermark from
  durable storage instead means this scoping actually helps in CI, not just when running dbt
  repeatedly on one machine.

  incremental_lookback_days (dbt_project.yml var, default 30) is a safety margin, not a precise
  cutoff: reconciliation can write backdated transactions to older raw/ paths - that's its whole
  job (docs/decisions/0001-reconciliation-as-source-of-truth.md) - and a window scoped exactly to
  the watermark would silently stop seeing those the moment the watermark moves past them. A
  margin bounds that risk to "reconciliation fell more than N days behind" rather than eliminating
  it - the weekly --full-refresh CI run (.github/workflows/dbt.yml) is the actual backstop that
  closes the gap regardless of margin size.

  DuckDB's read_json hard-errors if ANY path in a multi-glob list matches zero files, even when
  others in the same list match fine - candidate months are checked for existence via glob() and
  filtered out before ever being passed to read_json, not assumed to all have data.

  Falls back to a full unscoped scan whenever the scoped path can't be trusted: first run,
  --full-refresh, no staging/ output yet, or (belt and suspenders) no matching months found at all.
#}

{% macro raw_transaction_columns() %}
  {%- set merchant_struct = "STRUCT(id VARCHAR, name VARCHAR, category VARCHAR, emoji VARCHAR, online BOOLEAN, atm BOOLEAN)" -%}
  {{ return("{'source': 'VARCHAR', 'transaction': 'STRUCT(id VARCHAR, account_id VARCHAR, amount BIGINT, currency VARCHAR, created VARCHAR, settled VARCHAR, description VARCHAR, category VARCHAR, notes VARCHAR, is_load BOOLEAN, decline_reason VARCHAR, merchant " ~ merchant_struct ~ ")'}") }}
{% endmacro %}

{#
  Mirrors models/staging/_sources.yml's raw_transactions_glob var / az:// switch, duplicated here
  rather than shared: dbt-duckdb renders a source's external_location during project *parsing*,
  before custom macros exist, so this macro can't be called from there (see the sources.yml
  comment) - and there's no dbt API to pull a source's compiled FROM-clause text back out as a
  string to reuse it the other way around either.
#}
{% macro raw_transactions_base() %}
  {{ return('az://raw' if target.name == 'azure' else 'fixtures/raw') }}
{% endmacro %}

{% macro full_raw_transactions_scan() %}
  {%- set glob = raw_transactions_base() ~ '/**/*.json' -%}
  {{ return("read_json('" ~ glob ~ "', format='auto', union_by_name=true, columns=" ~ raw_transaction_columns() ~ ")") }}
{% endmacro %}

{#
  Returns None if incremental scoping shouldn't apply (--full-refresh / no staging/ output yet),
  otherwise the margin-adjusted watermark. Shared by scoped_raw_transactions_source() (what
  stg_transactions reads from raw/) and export_staging_transactions.sql (what it re-publishes to
  staging/), so the two can't drift out of sync with each other - they're scoping two different
  things (a read glob vs. a WHERE filter) but need to agree on the same cutoff, since a partition
  export_staging_transactions doesn't re-publish this run is one stg_transactions is trusting
  didn't change.

  Deliberately does NOT check is_incremental() - that reflects whether the *current* model being
  compiled is doing a full build, which is only meaningful for stg_transactions itself (the one
  model actually materialized `incremental`). export_staging_transactions is `external`, so
  is_incremental() would always evaluate false there regardless of what stg_transactions is doing -
  silently defeating the scoping entirely if this macro relied on it. scoped_raw_transactions_source()
  below checks is_incremental() itself, for itself, before ever calling this.

  Guarded by `execute`: dbt renders model Jinja during a parse-only introspection pass too (to
  extract ref()/source() dependencies for the DAG), before any real query connection exists -
  every dbt invocation does this, including plain `dbt parse`. run_query()'s result isn't safe to
  process in that pass (dbt-core returns something that isn't a real result table, and calling
  .columns on it throws a rather opaque 'None' has no attribute 'table'). `execute` is dbt's own
  flag for "this is the real run, not just parsing" - stg_transactions.sql happened to dodge this
  by accident, since is_incremental() short-circuits before ever reaching run_query() during that
  pass, but nothing here does that for free, so it's checked explicitly.
#}
{% macro incremental_scan_from() %}
  {%- if not execute or flags.FULL_REFRESH -%}
    {{ return(none) }}
  {%- endif -%}

  {%- set staging_glob = blob_location('staging') ~ '/**/*.parquet' -%}

  {%- set staging_exists_query -%}
    select count(*) as n from glob('{{ staging_glob }}')
  {%- endset -%}
  {%- set staging_exists = run_query(staging_exists_query).columns[0].values()[0] -%}
  {%- if staging_exists == 0 -%}
    {{ return(none) }}
  {%- endif -%}

  {%- set watermark_query -%}
    select max(created_at) as watermark from read_parquet('{{ staging_glob }}', union_by_name=true)
  {%- endset -%}
  {%- set watermark = run_query(watermark_query).columns[0].values()[0] -%}
  {%- if watermark is none -%}
    {{ return(none) }}
  {%- endif -%}

  {%- set margin_days = var('incremental_lookback_days', 30) -%}
  {{ return(watermark - modules.datetime.timedelta(days=margin_days)) }}
{% endmacro %}

{% macro scoped_raw_transactions_source() %}
  {#- is_incremental() is checked here, not inside incremental_scan_from() - see that macro's
      docstring for why. This is the one place it's actually meaningful: stg_transactions is the
      model materialized `incremental`, so this correctly detects "the local relation doesn't
      exist yet, dbt is about to do a full rebuild" and matches that with a full raw/ read. -#}
  {%- if not is_incremental() -%}
    {{ return(full_raw_transactions_scan()) }}
  {%- endif -%}

  {%- set scan_from = incremental_scan_from() -%}
  {%- if scan_from is none -%}
    {{ return(full_raw_transactions_scan()) }}
  {%- endif -%}

  {%- set today = modules.datetime.datetime.utcnow().date() -%}

  {#- Month-granularity candidates from scan_from's month through the current month. -#}
  {%- set month_count = ((today.year - scan_from.year) * 12 + (today.month - scan_from.month)) + 1 -%}
  {%- set months = [] -%}
  {%- for i in range(0, month_count) -%}
    {%- set total_month = scan_from.month - 1 + i -%}
    {%- set year = scan_from.year + (total_month // 12) -%}
    {%- set month = (total_month % 12) + 1 -%}
    {%- do months.append('%04d/%02d' % (year, month)) -%}
  {%- endfor -%}

  {%- set raw_base = raw_transactions_base() -%}
  {%- set existence_checks = [] -%}
  {%- for ym in months -%}
    {%- set g = raw_base ~ '/' ~ ym ~ '/**/*.json' -%}
    {%- do existence_checks.append("select '" ~ g ~ "' as pattern, count(*) as file_count from glob('" ~ g ~ "')") -%}
  {%- endfor -%}
  {%- set existence_query = existence_checks | join('\nunion all\n') -%}
  {%- set existence_result = run_query(existence_query) -%}

  {%- set matched_globs = [] -%}
  {%- for row in existence_result.rows -%}
    {%- if row['file_count'] > 0 -%}
      {%- do matched_globs.append(row['pattern']) -%}
    {%- endif -%}
  {%- endfor -%}

  {%- if matched_globs | length == 0 -%}
    {{ return(full_raw_transactions_scan()) }}
  {%- endif -%}

  {%- set glob_list = "['" ~ (matched_globs | join("', '")) ~ "']" -%}
  {{ return("read_json(" ~ glob_list ~ ", format='auto', union_by_name=true, columns=" ~ raw_transaction_columns() ~ ")") }}
{% endmacro %}
