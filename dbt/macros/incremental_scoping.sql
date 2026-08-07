{#
  Scopes stg_transactions' raw/ read to a recent date window instead of scanning every file in
  raw/ on every run - the naive full glob became an ~8 minute (and growing, now ~17-20 min at
  ~5,000 files) bottleneck once raw/ held years of individual per-transaction JSON files (one
  blob per transaction, by design - see functions/shared/blob_writer.py).

  The watermark comes from staging/'s already-published Parquet (durable, in Blob Storage), not
  the local incremental table. This isn't just a nice-to-have: stg_transactions is materialized as
  a plain `table`, not `incremental` - it's rebuilt fresh every run by unioning this scoped raw/
  read with the *existing* staging/ output (see stg_transactions.sql), rather than merging into a
  persisted local relation the way dbt's `incremental` materialization does. That's deliberate:
  GitHub Actions runners are ephemeral, so a local relation never survives between CI runs, which
  made an earlier is_incremental()-gated version of this scoping silently inert in CI - every
  `publish` job fell through to a full unscoped scan regardless, since `is_incremental()` was
  always false there. Durable storage doesn't have that problem, so everything here keys off it.

  incremental_lookback_days (dbt_project.yml var, default 30) is a safety margin, not a precise
  cutoff: reconciliation can write backdated transactions to older raw/ paths - that's its whole
  job (docs/decisions/0001-reconciliation-as-source-of-truth.md) - and a window scoped exactly to
  the watermark would silently stop seeing those the moment the watermark moves past them. A
  margin bounds that risk to "reconciliation fell more than N days behind" rather than eliminating
  it - the weekly --full-refresh CI run (.github/workflows/dbt.yml) is the actual backstop that
  closes the gap regardless of margin size.

  The returned watermark is snapped back to the first of its month, which is load-bearing rather
  than cosmetic - see docs/decisions/0018-partition-aligned-incremental-window.md. staging/ is
  Hive-partitioned by month and DuckDB's partitioned COPY rewrites a touched partition *in full*
  from whatever the SELECT returns, so a day-granular watermark made export_staging_transactions
  republish its oldest partition containing only the days after the watermark - silently dropping
  the earlier days of that month from staging/. Month-aligning here means every partition the
  export rewrites is rewritten complete, and it costs nothing on the read side because
  scoped_raw_transactions_source() below already scans whole months anyway.

  DuckDB's read_json hard-errors if ANY path in a multi-glob list matches zero files, even when
  others in the same list match fine - candidate months are checked for existence via glob() and
  filtered out before ever being passed to read_json, not assumed to all have data.

  Falls back to a full unscoped scan whenever the scoped path can't be trusted: first run,
  --full-refresh, no staging/ output yet, or no matching months found at all.

  That last case looks like a "no work to do" shortcut being answered with the most expensive
  possible query, but it is genuinely the correct response and must not be optimised into an empty
  read. staging/'s newest partition is *derived from* raw/, so the scan window always contains at
  least one raw blob by construction - zero matches means raw/ no longer agrees with staging/
  (blobs deleted, container remounted, prefix renamed). In that state a scoped read would union an
  empty new_read with an `existing` deliberately filtered to months *before* the window, quietly
  dropping the window's months from the output entirely. The full scan rebuilds from raw/ instead,
  which is both correct and self-correcting.
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
  Returns None if scoping shouldn't apply (--full-refresh / no staging/ output yet), otherwise the
  margin-adjusted watermark. Shared by stg_transactions.sql (both to scope its raw/ read via
  scoped_raw_transactions_source() below, and to decide whether it needs to union in the existing
  staging/ output at all) and export_staging_transactions.sql (to scope its WHERE filter) - all
  three need to agree on the same cutoff, or stg_transactions and its own published output could
  disagree about which months are "new" vs "already covered".

  No longer gated on is_incremental(): an earlier version only called this when
  is_incremental() was true, which seemed reasonable (stg_transactions was the one model actually
  materialized `incremental`) but silently defeated the whole thing in CI - GitHub Actions runners
  are ephemeral, so the local relation is_incremental() checks for never exists there, meaning it
  was always false and this scoping never activated on a single real CI run. stg_transactions is
  materialized as a plain `table` now specifically so correctness doesn't depend on local state -
  see its own file for how.

  Guarded by `execute`: dbt renders model Jinja during a parse-only introspection pass too (to
  extract ref()/source() dependencies for the DAG), before any real query connection exists -
  every dbt invocation does this, including plain `dbt parse`. run_query()'s result isn't safe to
  process in that pass (dbt-core returns something that isn't a real result table, and calling
  .columns on it throws a rather opaque 'None' has no attribute 'table').
#}
{% macro incremental_scan_from() %}
  {%- if not execute or flags.FULL_REFRESH -%}
    {{ return(none) }}
  {%- endif -%}

  {#- Watermark comes from the *partition path names* (a cheap glob/listing call, ~1s even for
      85 partitions), not from reading any actual Parquet data. An earlier version used
      `read_parquet(..., union_by_name=true)` to get max(created_at) directly, which has to open
      and read every matching file's footer to do that union - ~24s locally for 85 partitions.
      Parsing the latest transaction_year=/transaction_month= out of the path string instead means
      this is a listing operation, not a data read, so it stays cheap regardless of how many
      partitions exist - it's the same property scoped_raw_transactions_source() already relies on
      `glob()` for below. -#}
  {%- set staging_glob = blob_location('staging') ~ '/**/*.parquet' -%}

  {%- set listing_query -%}
    select max(file) as latest_path from glob('{{ staging_glob }}')
  {%- endset -%}
  {%- set latest_path = run_query(listing_query).columns[0].values()[0] -%}
  {%- if latest_path is none -%}
    {{ return(none) }}
  {%- endif -%}

  {#- Normalize backslashes first: local (dev target) glob() results use OS-native separators,
      which are backslashes on Windows. -#}
  {%- set normalized_path = latest_path.replace('\\', '/') -%}
  {%- set year = normalized_path.split('transaction_year=')[1].split('/')[0] | int -%}
  {%- set month = normalized_path.split('transaction_month=')[1].split('/')[0] | int -%}
  {%- set latest_month_start = modules.datetime.datetime(year, month, 1) -%}

  {%- set margin_days = var('incremental_lookback_days', 30) -%}
  {%- set margin_start = latest_month_start - modules.datetime.timedelta(days=margin_days) -%}

  {#- Snap to the first of the month (see the partition-alignment note in the header). This only
      ever widens the window - the effective margin becomes "at least incremental_lookback_days,
      rounded out to a whole month" - so it can't cause the scoping to miss anything. -#}
  {{ return(margin_start.replace(day=1)) }}
{% endmacro %}

{#
  Takes the already-computed scan_from (see incremental_scan_from()) rather than calling it
  itself, so stg_transactions.sql can compute it once and reuse the same value both here and to
  decide whether it needs to union in the existing staging/ output.
#}
{% macro scoped_raw_transactions_source(scan_from) %}
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
