-- Publication check: the Parquet actually written to staging/ contains exactly what
-- stg_transactions modelled - no missing rows, no stale extras, no duplicates.
--
-- This is the direct regression test for docs/decisions/0018-partition-aligned-incremental-window.
-- export_staging_transactions rewrites a touched partition *in full* from its SELECT, so a filter
-- that cuts a partition in half republishes that month containing only the rows after the cutoff
-- and silently drops the rest. When that was live, stg_transactions held 4,993 rows and staging/
-- held 4,986, and nothing failed: every mart re-derives from stg_transactions, so only the
-- published artifact had the hole - which is exactly what mcp_server reads (its `staging` view,
-- and get_data_quality_report through it). Only a test that reads the written files back catches
-- a divergence between what dbt computed and what dbt published.
--
-- Reads the real files rather than ref()-ing the external model for that reason: ref() would
-- resolve to dbt-duckdb's registered view, which is a restatement of the SELECT, not evidence
-- about what landed in Blob Storage. The ref below is a dependency hint only, so this test is
-- ordered after the export rather than racing it.
-- depends_on: {{ ref('export_staging_transactions') }}
--
-- Duplicates get their own branch because EXCEPT is set-based and would not see them: the same
-- transaction_id written into two different month partitions (a created_at change moving a row
-- without the old partition being rewritten) leaves both set comparisons clean.

with published as (

    select transaction_id
    from read_parquet('{{ blob_location("staging") }}/**/*.parquet', hive_partitioning=true)

),

modelled as (

    select transaction_id from {{ ref('stg_transactions') }}

),

missing_from_published as (

    select 'in_stg_transactions_but_not_published_to_staging' as issue, transaction_id
    from (select transaction_id from modelled except select transaction_id from published)

),

unexpected_in_published as (

    select 'published_to_staging_but_not_in_stg_transactions' as issue, transaction_id
    from (select transaction_id from published except select transaction_id from modelled)

),

duplicated_in_published as (

    select 'duplicated_across_staging_partitions' as issue, transaction_id
    from published
    group by transaction_id
    having count(*) > 1

)

select * from missing_from_published
union all
select * from unexpected_in_published
union all
select * from duplicated_in_published
