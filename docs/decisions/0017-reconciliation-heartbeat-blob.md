# 0017. Detecting a dead pipeline with a heartbeat blob and a scheduled health check

Status: Accepted
Date: 2026-08-07

Supersedes the "path forward" left open in [ADR-0010](0010-reconciliation-heartbeat-alert.md).

## Context

[ADR-0010](0010-reconciliation-heartbeat-alert.md) identified the gap - nothing detects
reconciliation silently dying, most plausibly via a revoked or expired Monzo refresh token - and
rejected the Azure Monitor scheduled query rule that would have closed it, on cost ($1-3/month,
against this project's zero-tolerance stance). It left the gap explicitly unaddressed and sketched
a free replacement: the same heartbeat *logic*, executed from a scheduled GitHub Actions workflow.

Three things had to be resolved to actually build that.

**What signal to check.** The obvious candidate is transaction freshness - alert when
`max(created_at)` in `stg_transactions` falls behind. It doesn't work: a personal current account
routinely goes days without a transaction, so "no spending happened" and "ingestion is dead" are
the same observation. Any threshold loose enough to avoid false alarms over a quiet week is too
loose to detect a real outage promptly. The same ambiguity is already called out in
`get_data_quality_report`'s docstring, which notes it can only report data recency, not whether
ingestion actually ran.

The distinguishing signal has to come from the ingestion path itself, and nothing in the system
emitted one - Application Insights holds the execution telemetry, but querying it is precisely the
paid path ADR-0010 rejected.

**Where a heartbeat can live.** `raw/` is the natural home for anything the reconcile Function
writes, but the Event Grid subscription is subject-filtered to `raw/`
([ADR-0011](0011-event-grid-trigger-for-dbt-pipeline.md)) - a heartbeat there would dispatch a full
dbt pipeline run every 6 hours forever, for a blob containing no transaction data.

**Who watches the watchers.** A scheduled GitHub Actions workflow can detect a dead Function, but
not its own absence. GitHub disables *all* scheduled workflows in a repository after 60 days
without repository activity, and scheduled runs themselves don't reset that timer. Since this
project already drives reconciliation ([ADR-0013](0013-externally-triggered-reconciliation.md)) and
the nightly dbt build from GitHub crons, a quiet 60 days would stop ingestion, transformation and
monitoring together - with no failed run anywhere to notice, because nothing would run at all.

## Decision

Three parts:

1. **`reconcile` writes a heartbeat blob** (`ops/reconcile-heartbeat.json`) after every successful
   run, recording `last_run_at` and `transactions_written`. Written *after* the write loop
   completes, so a run that raises partway leaves the previous heartbeat in place to go stale.
   A run that legitimately finds zero transactions still records one - that's what separates a
   quiet week from a broken pipeline.

2. **A new `ops` container**, separate from the `raw`/`staging`/`marts` medallion layers, holding
   operational signals rather than pipeline data. Keeps the Event Grid subject filter intact and
   keeps the dbt identity's data-layer RBAC unchanged. CI gets container-scoped
   `Storage Blob Data Reader` on it; the Function App already writes via its account-scoped
   `Storage Blob Data Owner` grant.

3. **`.github/workflows/pipeline_health.yml`**, running daily, which fails when the heartbeat is
   older than 24h (reconcile runs 6-hourly, so this tolerates three consecutive misses) or when
   `marts/monthly_cashflow.parquet` was last written more than 48h ago (dbt publishes nightly at
   minimum). A failed scheduled workflow emails the repository owner - the free notification
   channel ADR-0010 was after. The same workflow carries a monthly `keepalive` job that commits a
   timestamp to `.github/last-active`, a path deliberately matched by no other workflow's `paths:`
   filter, purely to reset GitHub's 60-day inactivity timer.

## Consequences

- The gap ADR-0010 left open is closed at no recurring cost. Detection latency is worse than the
  rejected Azure Monitor rule (up to ~24h rather than continuous evaluation), which is an
  acceptable trade for a personal pipeline whose data is reconstructible from the Monzo API.
- Checking blob *last-modified* for the dbt half rather than row counts means the check asks "did
  the pipeline run" instead of "did the numbers change" - an unchanged mart with a recent
  timestamp is a healthy quiet period, not a failure. It does not detect dbt publishing wrong
  results, only dbt not publishing.
- The heartbeat keeps only the most recent run. Historical execution data stays in Application
  Insights; this is deliberately a liveness signal, not an audit log.
- The keepalive commits one bot commit per month to `master`. That is real (if small) history
  noise, accepted because the alternative failure mode is the entire pipeline stopping silently.
  It becomes unnecessary if the repository is otherwise active every 60 days, but relying on that
  would make pipeline liveness depend on developer habit.
- `get_data_quality_report` in `mcp_server/` still reports only data recency, not ingestion
  liveness. The heartbeat is now the signal it would need to report the latter; wiring it in is
  deferred, not blocked.
