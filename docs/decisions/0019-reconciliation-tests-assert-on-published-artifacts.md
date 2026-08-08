# 0019. Reconciliation tests assert on published artifacts, not dbt's own relations

Status: Accepted
Date: 2026-08-08

## Context

The spec's Data Quality section asks for "reconciliation checks (row counts / sums between raw and
staging, and between Monzo API totals and warehouse totals)". Nothing implemented them. Every test
in the project was column-level — `unique`, `not_null`, `accepted_values`, `relationships` — which
answers "is each row well-formed?" and never "did all the rows arrive?".

[ADR-0018](0018-partition-aligned-incremental-window.md) is the proof that this gap was real rather
than theoretical. A day-granular watermark republished a month partition containing only the days
after it, dropping seven transactions from `staging/`. Every test passed throughout, because the
surviving rows were individually valid and every mart re-derives from `stg_transactions` (which
re-reads the full month from `raw/`), so only the *published artifact* had the hole. The weekly
`--full-refresh` kept healing it, which is why it looked like nothing rather than like corruption.

Two things follow from that incident, and they shape the design more than the tests themselves:

1. **Testing dbt's in-catalog relations would not have caught it.** `stg_transactions` was correct.
   The defect existed only in the Parquet written to Blob Storage — which is what `mcp_server` and
   `scripts/query_marts.py` read. A test that asserts on `ref()` asserts on a restatement of the
   model's SELECT, not on evidence about what landed in storage.
2. **A test whose inputs all come from the same DAG cannot detect a consistent scoping bug.** If the
   incremental window silently dropped history, `stg_transactions` and everything downstream of it
   would agree with each other perfectly. At least one test has to read something the DAG does not
   produce.

## Decision

Three singular tests in `dbt/tests/`, all `severity: error`, all running on both targets:

- **`assert_raw_blobs_reconcile_to_stg_transactions`** — the independent-input test. Compares the
  set of transaction IDs in `raw/` against `stg_transactions`, both directions.
- **`assert_staging_export_matches_stg_transactions`** — the direct ADR-0018 regression. Reads the
  Parquet actually written to `staging/` back and compares it to what the model computed, including
  a duplicate check (set comparison alone cannot see the same ID written into two partitions).
- **`assert_marts_reconcile_to_fct_transactions`** — sum and count reconciliation between each
  published mart and `fct_transactions` restated under the mart's own filters.

Two design points worth stating explicitly, because both look wrong at first glance:

**The raw/ test reads no JSON.** `raw/` is one blob per transaction named `<transaction_id>.json`
(`functions/shared/blob_writer.py`), so the full ID set is recoverable from the path listing alone.
This is the same property `incremental_scan_from()` already exploits to derive its watermark from
`staging/` partition *names* rather than from Parquet footers. A `read_json` over ~5,000 files takes
minutes and would reintroduce exactly the cost the incremental scoping exists to avoid; `glob()`
over the same files is a listing call. Measured against live storage: 4,997 blobs listed, parsed and
compared in **2.6s**.

**The tests read the published files rather than `ref()`-ing the external models.** The `ref()`s are
present as `-- depends_on:` hints for DAG ordering only. Reading the artifact is the entire point —
see the first numbered item above.

**The current UTC day is excluded from both sides of the `raw/` test.** `raw/` is written
continuously by the webhook and 6-hourly by reconciliation, while dbt's read of `raw/` happens
minutes before the test runs. A blob landing in that gap is a live pipeline working correctly, and
failing the nightly build over it would train the failure to be ignored — the worst outcome for a
test whose value depends on being believed. Today's data is checked by the next run.

## Consequences

Reconciliation and completeness are now enforced rather than assumed, and the enforcement covers the
published artifacts the query layer actually reads — the ADR-0018 failure mode fails the build
instead of hiding until a `--full-refresh` heals it. Both negative cases were verified before
merging: removing a `raw/` blob fails the first test, removing a `staging/` partition fails the
second with the ADR-0018 shape (model correct, artifact short).

Cost is roughly **5s on a ~48s `azure` run** — the tests take 1.4s / 5.0s / 13.5s individually but
overlap with other work at 4-thread model concurrency. The `staging/` test is the expensive one
because it reads all 85+ partitions; that is the price of asserting on the artifact rather than the
relation, and it is accepted deliberately.

Two costs accepted:

- **A residual race remains.** Reconciliation writing a *backdated* transaction (older `created`,
  hence an older `raw/` path) mid-run would fail the first test legitimately-looking. Excluding the
  current day does not cover it, because the path date is the transaction's date, not the write
  time. This is rare enough to be worth a re-run rather than more machinery, and the test header
  says so, so a future failure is not a mystery.
- **The mart test restates each mart's filters** (`is_debit`, `not is_declined`,
  `merchant_id is not null`). That duplication is the mechanism — a filter silently changing in a
  mart moves the published total away from the fact table — but it does mean a *deliberate* filter
  change requires updating the test alongside the model.

Money columns are `DOUBLE` (`amount_minor_units / 100.0`), so mart sums are compared to within half
a penny rather than exactly; summing the same values in a different grouping order is free to differ
in the last bits. Counts are integers and compared exactly.

Source freshness was deliberately **not** added alongside these, despite the spec listing it in the
same section. On a personal account "no spending for three days" and "the refresh token was revoked"
are the same observation, so a freshness test would produce false alarms rather than signal — the
reason [ADR-0017](0017-reconciliation-heartbeat-blob.md) put that signal in a heartbeat the
ingestion path emits itself. These tests answer "is the data complete?", the heartbeat answers "is
ingestion alive?", and conflating them would weaken both.
