-- Completeness check: every transaction that exists in raw/ reaches stg_transactions, and
-- stg_transactions invents nothing that isn't in raw/. This is the spec's "row counts between raw
-- and staging" reconciliation control (Data Quality section), and the only test here that reads an
-- input independent of the dbt DAG - every other test compares dbt's output against dbt's own
-- other output, so a scoping bug that drops history consistently would satisfy all of them.
--
-- It is cheap despite covering all of raw/ history, because it never opens a single JSON file.
-- raw/ is one blob per transaction named <transaction_id>.json (functions/shared/blob_writer.py),
-- so the id set is recoverable from the *path listing* alone - the same property
-- incremental_scan_from() exploits to derive its watermark from staging/ partition names rather
-- than from Parquet footers. A read_json over ~5,000 files takes minutes; glob() over the same
-- files is a listing call.
--
-- This is the test that would have caught docs/decisions/0018: the incremental scoping silently
-- dropped days from a partition, and every existing test passed because they were all column-level
-- (unique/not_null/accepted_values) and the surviving rows were individually valid.
--
-- Deliberately ignores the current UTC day on both sides. raw/ is written continuously by the
-- webhook and 6-hourly by reconciliation, and dbt's read of raw/ happens minutes before this test
-- runs - a blob landing in that gap is a live pipeline working correctly, not a defect, and
-- failing the nightly build over it would train the failure to be ignored. Today's data is checked
-- by the next run. Note the residual race this does NOT cover: reconciliation writing a *backdated*
-- transaction (older created date, hence an older raw/ path) mid-run would fail this legitimately-
-- looking. That's rare enough to be worth a rerun rather than more machinery - if a failure here
-- lists a handful of ids that are present in raw/ on inspection, re-run before investigating.

with raw_blobs as (

    select
        regexp_extract(file, '([^/\\]+)\.json$', 1) as transaction_id,
        regexp_extract(file, '(\d{4})[/\\](\d{2})[/\\](\d{2})[/\\][^/\\]+\.json$', ['y', 'm', 'd']) as path_parts
    from glob('{{ raw_transactions_base() }}/**/*.json')

),

raw_ids as (

    select transaction_id
    from raw_blobs
    where try_cast(path_parts.y || '-' || path_parts.m || '-' || path_parts.d as date)
        < (now() at time zone 'UTC')::date

),

modelled_ids as (

    select transaction_id
    from {{ ref('stg_transactions') }}
    where created_at < (now() at time zone 'UTC')::date

),

missing_from_model as (

    select 'in_raw_but_not_in_stg_transactions' as issue, transaction_id
    from (select transaction_id from raw_ids except select transaction_id from modelled_ids)

),

missing_from_raw as (

    select 'in_stg_transactions_but_not_in_raw' as issue, transaction_id
    from (select transaction_id from modelled_ids except select transaction_id from raw_ids)

)

select * from missing_from_model
union all
select * from missing_from_raw
