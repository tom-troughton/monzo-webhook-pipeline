# 0018. The incremental watermark is snapped to a partition boundary

Status: Accepted
Date: 2026-08-07

## Context

`stg_transactions` scopes its `raw/` read to a recent window, and `export_staging_transactions`
scopes its republish of `staging/` to the same window (see `dbt/macros/incremental_scoping.sql`).
Both key off one watermark from `incremental_scan_from()`.

The two used that watermark at different granularities, and it silently lost data:

- the read side expanded it to **whole months** — `read_json(['az://raw/2026/07/**', 'az://raw/2026/08/**'])`
- the write side used it **verbatim, day-granular** — `where created_at >= '2026-07-02'`

`incremental_scan_from()` returns `first-of-latest-staging-month - incremental_lookback_days`, which
lands mid-month for any 31-day month (and up to 29 days into a month when the margin crosses
February). That was assumed harmless because "DuckDB's partitioned COPY only touches partitions
present in the result set" — true, but incomplete. A partition that *is* present gets rewritten
**in full from the result set**. So the oldest touched partition was republished containing only the
days after the watermark, and the earlier days of that month were dropped from `staging/`.

Confirmed against live storage before the fix: `raw/2026/07/01/` held 7 blobs, while the published
`staging/transaction_year=2026/transaction_month=07/` partition began at 2026-07-02. Every other day
matched `raw/` exactly. `stg_transactions` held 4,993 rows; `staging/` held 4,986.

The bug hid well because `stg_transactions` re-reads the whole month from `raw/` on every run, so
the table and every downstream mart stayed correct. Only the published `staging/` artifact had the
hole — which is what `mcp_server`'s `staging` view and `get_data_quality_report` read. The weekly
`--full-refresh` ([ADR-0001](0001-reconciliation-as-source-of-truth.md)'s backstop) healed it, and
the next incremental run re-opened it, so it never persisted long enough to look like corruption.

## Decision

`incremental_scan_from()` returns a watermark snapped back to the first of its month
(`margin_start.replace(day=1)`). The alignment lives in the one place both consumers read from,
rather than being re-derived at each call site.

This rests on a layout coincidence that is now stated explicitly rather than assumed:
`functions/shared/blob_writer.py` writes `raw/%Y/%m/%d/<id>.json` from `transaction.created`, and
`export_staging_transactions` partitions `staging/` by `created_at`'s year/month. **The raw prefix
granularity and the staging partition granularity are the same, and must stay in step.** Because of
that, `stg_transactions` also filters its `existing` branch by partition predicate
(`transaction_year::int * 100 + transaction_month::int < <watermark month>`) rather than by
anti-joining against the new read — the two are equivalent, and the predicate is not a NULL trap.

The general rule: **the export's filter must be aligned to the partition key, not to the
watermark.** Any future change to either the `raw/` path layout or the `staging/` partition key has
to preserve that.

## Consequences

- The seven missing transactions return on the next incremental run — the window already covers July,
  so the partition is simply republished complete. No manual `--full-refresh` needed to heal it.
- The effective lookback becomes "at least `incremental_lookback_days`, rounded out to a whole
  month" — 30–60 days rather than exactly 30. Strictly wider, so it cannot cause the scoping to miss
  anything; it costs a little more raw/ reading in exchange for the alignment guarantee.
- Partition granularity is now load-bearing and can't be tuned freely. Coarsening `staging/` to
  yearly partitions (tempting: 8 files instead of 85, and the per-blob round-trip is the dominant
  read cost) would force the export to rewrite whole *year* partitions, which would force the raw
  read to cover a whole year to keep them complete — strictly worse. Monthly is the right granularity
  precisely because `raw/` is pathed monthly.
- The read-side fallback to a full unscoped scan when no months match is now documented as
  load-bearing rather than defensive, and must not be "optimised" into an empty read. Zero matches
  means `raw/` and `staging/` disagree, and in that state a scoped read would drop the window's
  months entirely.
- The invariant is not enforced by a test. A `staging/`-vs-`raw/` row-count reconciliation check
  would catch a regression directly; the spec's Data Quality section already wants one, and this is
  a concrete argument for building it.
