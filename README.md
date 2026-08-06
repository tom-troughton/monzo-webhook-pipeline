# Personal Finance Data Platform

A production-inspired data engineering platform built around my own Monzo transaction data — event-driven
ingestion, API reconciliation, incremental transformation with dbt/DuckDB, and a governed query layer
exposed over MCP. Built as a portfolio project to demonstrate patterns used in real data platforms, on a
strict personal-Azure-subscription budget.

Full spec: [docs/Personal_Finance_Data_Platform_Project_Spec_v2.md](docs/Personal_Finance_Data_Platform_Project_Spec_v2.md).
Rationale for individual design decisions: [docs/decisions/](docs/decisions/) (ADRs).

## Architecture

```text
Monzo Webhook                              Monzo API
      │                                         │
      ▼                                         │ fetched ~6-hourly, triggered by
Azure Function (HTTP)                           │ a GitHub Actions cron - not a
  validate secret path + payload,                │ native Timer trigger (see "A
  write straight to raw/ - no queue               │ debugging story" below)
  in between (see ADR-0016)                      ▼
      │                              Azure Function (HTTP)
      │                                fetch + write to raw/
      ▼                                         │
            Blob Storage — raw/ (immutable JSON)
                          │
                          ▼
             Event Grid (BlobCreated, raw/ only)
                          │
                          ▼
          Azure Function (HTTP, Event Grid webhook)
              → GitHub repository_dispatch
                          │
                          ▼
       GitHub Actions → dbt (incremental models,
              DuckDB as execution engine)
        (also nightly cron + manual, as a fallback
         if the event-driven path is ever missed)
                          │
                          ▼
     Blob Storage — staging/ + marts/ (curated Parquet)
                          │
                          ▼
      Python MCP Server ── curated tools only
     (mcp_server/, runs locally/on-demand via
    stdio, not hosted - scripts/query_marts.py
       remains for ad-hoc SQL the tools don't cover)
                          │
                          ▼
                 LLM / Chat Client
```

Webhooks are treated as low-latency notifications, never as the source of truth — the scheduled
reconciliation job against the Monzo API is authoritative. See
[ADR-0001](docs/decisions/0001-reconciliation-as-source-of-truth.md).

**Every trigger in this pipeline is HTTP**, which wasn't the original design — see below.

## A debugging story worth reading

The original design used Azure-native triggers throughout: a Timer trigger for reconciliation, a
Storage Queue + queue trigger for both the webhook write and the Event Grid → dbt hookup, and Event
Grid delivering directly to the Function App. Getting the pipeline to actually run in production
surfaced that almost none of that worked as documented, on the specific hosting plan this project
ended up on (Flex Consumption, itself a fallback after the originally-planned plan hit an
unresolved Azure capacity quota — [ADR-0012](docs/decisions/0012-flex-consumption-hosting-plan.md)):

- **Event Grid → Function App directly** failed with a platform-level endpoint-validation error —
  confirmed as a genuine Azure bug, not a config mistake, by reproducing it identically through
  both Terraform *and* the Azure Portal UI directly. ([ADR-0011](docs/decisions/0011-event-grid-trigger-for-dbt-pipeline.md))
- **Timer triggers don't reliably fire** on a scaled-to-zero Flex Consumption app — confirmed via
  Application Insights showing zero invocations across two missed scheduled ticks, only waking on
  an unrelated HTTP request. Fixed by driving reconciliation from a GitHub Actions cron instead of
  Azure's own scheduler. ([ADR-0013](docs/decisions/0013-externally-triggered-reconciliation.md))
- **Queue triggers have the same problem.** A Storage Queue was tried as the Event Grid destination
  instead; Event Grid's own metrics confirmed every event was published and delivered successfully,
  but the queue-triggered function never consumed any of them. Fixed by switching Event Grid to
  call an HTTP endpoint directly, implementing its subscription-validation handshake in code.
  ([ADR-0015](docs/decisions/0015-event-grid-webhook-endpoint.md))
- **The webhook's own queue buffer got removed pre-emptively** once queue triggers were known
  unreliable — rather than wait for it to fail silently too, `webhook` now writes to `raw/`
  directly. ([ADR-0016](docs/decisions/0016-webhook-writes-directly-no-queue.md))
- Smaller findings along the way: a missing app setting that only "worked" locally because of a
  `.env` file that never deploys; a Key Vault role that was read-only when the design always
  required write access; the Functions host's own internal secret-key management failing under
  identity-only storage auth; `func` CLI's post-deploy health check reporting false failures.

None of this was caught by the unit test suite (which passes cleanly throughout and mocks every
Azure/Monzo call) — it's the kind of thing that only shows up by exercising the real deployed
system, which is exactly what happened. See [docs/decisions/](docs/decisions/) for the full,
evidence-based trail on each one.

## What this project demonstrates

- **Reliable ingestion under an unreliable delivery guarantee** — webhook + reconciliation +
  idempotent writes, rather than trusting a single webhook call
  ([ADR-0001](docs/decisions/0001-reconciliation-as-source-of-truth.md)).
- **Diagnosing real platform bugs, not just assuming it's your own code** — every claim above is
  backed by direct evidence (Application Insights queries, Event Grid delivery metrics, reproducing
  a failure through two independent tools) rather than guesswork, and the architecture was adapted
  to what was actually confirmed to work, not what the docs said should work.
- **Infrastructure as code with real guardrails** — Terraform modules plus a subscription-wide Azure
  Policy module (`cost_guardrails`) that denies VM creation and restricts SKUs to non-Premium tiers,
  so a mistake can't silently produce a large bill.
- **Cost discipline as a first-class constraint**, not an afterthought — every resource choice is
  checked against Azure's always-free grants before being provisioned. A proposed Azure Monitor
  heartbeat alert for a dead reconciliation job was fully designed, then rejected once it priced
  out at $1-3/month outside the free tier ([ADR-0010](docs/decisions/0010-reconciliation-heartbeat-alert.md)).
  See the "Cost discipline" section in [CLAUDE.md](CLAUDE.md).
- **Secretless CI** — GitHub Actions authenticates to Azure via OIDC federated credentials, not a
  stored Service Principal secret, for both the infra/app deploy pipeline and the dbt pipeline
  ([ADR-0005](docs/decisions/0005-oidc-for-github-actions.md)). One deliberate, scoped exception:
  Azure calling *out* to GitHub's API has no OIDC equivalent, so a single fine-grained PAT is used
  there ([ADR-0011](docs/decisions/0011-event-grid-trigger-for-dbt-pipeline.md)).
- **Designing for real data, not just the happy path** — real Monzo API responses immediately broke
  assumptions synthetic test fixtures had masked (optional fields omitted rather than sent as
  `null`, empty-string sentinels instead of `null`, an unanticipated category value) - the dbt
  layer now declares an explicit schema instead of relying on inference, and a taxonomy-drift test
  warns instead of hard-failing the pipeline. See the dbt bullet in [CLAUDE.md](CLAUDE.md)'s
  "Current state" for the specifics.
- **A decision log, not just code** — every non-obvious architectural choice, including ones later
  reversed as new evidence came in (rejecting ADLS Gen2 hierarchical namespace, reversing the
  webhook's own queue buffer once queue triggers proved unreliable), is written down with its
  reasoning in [docs/decisions/](docs/decisions/).

## Tech stack

Azure Functions (Flex Consumption) · Azure Blob Storage · Azure Event Grid · Azure Key Vault ·
Terraform · Python · DuckDB · dbt · GitHub Actions · MCP

## Current status

Fully built and deployed - infrastructure, Function App, dbt pipeline, and MCP server are all live.

- **Infrastructure** (`terraform/`): resource group, storage account (`raw/`, `staging/`, `marts/`
  containers, RBAC least-privileged per identity — see [CLAUDE.md](CLAUDE.md) for the exact grants),
  Key Vault, Function App module (Flex Consumption, managed-identity-only access), Event Grid,
  `cost_guardrails` (subscription-wide Azure Policy: no VMs, no Premium SKUs), and `github_oidc`
  (federated credentials, no stored Azure secret).
- **Function App code** (`functions/`): every trigger is HTTP, driven externally where Azure's own
  native triggers proved unreliable — see "A debugging story worth reading" above.
  - `webhook` — validates the path secret + payload, writes straight to `raw/`.
  - `reconcile` — fetches recent transactions from the Monzo API, invoked ~6-hourly by
    `.github/workflows/reconcile.yml`.
  - `on_raw_data_created` — Event Grid's webhook destination for new `raw/` blobs, triggers the dbt
    pipeline via GitHub's `repository_dispatch` API.
  Shared Monzo auth (with a blob-lease lock around token refreshes - Monzo forbids concurrent
  refresh attempts, see [ADR-0014](docs/decisions/0014-monzo-refresh-token-locking.md)),
  blob-writer, and validation modules, with pytest coverage (all mocked — no real Monzo/Azure calls
  in tests).
- **dbt project** (`dbt/`), verified end-to-end against both local synthetic fixtures and real Blob
  Storage: `stg_transactions` (incremental, deduping webhook vs. reconciliation sources) →
  dimension/fact models → 4 curated marts, materialized straight to Parquet in `staging/`/`marts/`.
  Two targets - `dev` (local fixtures, no cloud calls) and `azure` (the real containers, via
  DuckDB's `azure` extension with OIDC/`credential_chain` auth, no stored secret).
- **`.github/workflows/`**: `deploy.yml` (Terraform plan/apply + Function publish, OIDC),
  `dbt.yml` (dbt build against fixtures on every PR; against real Blob Storage on push to
  `master`, nightly cron, manual dispatch, or `repository_dispatch` from the Event Grid handler),
  and `reconcile.yml` (the external trigger replacing the native Timer trigger).
- **`raw/`/`staging/`/`marts/` hold my real transaction history**, not synthetic data.
- **Operational scripts** (`scripts/`): one-time OAuth bootstrap, webhook registration, API sanity
  checks, a one-off historical backfill, and `query_marts.py` for ad-hoc SQL against the real marts.
- **MCP server** (`mcp_server/`): the 5 curated tools the spec names — `get_spend_by_category`,
  `get_monthly_cashflow`, `get_top_merchants`, `get_subscriptions`, `get_data_quality_report` — over
  the same marts, plus pytest coverage against an in-memory DuckDB (no real Azure access needed to
  run the tests). Runs locally/on-demand over stdio (`python -m mcp_server.server`), not hosted, per
  the spec's intent.

**Not built, by design:** dbt docs hosting (the site can be generated, just isn't hosted anywhere -
low priority for a project this size; GitHub Pages would be the natural free option if pursued),
on-demand backfill for an arbitrary date range (the spec mentions it, out of scope for now), ADLS
Gen2 hierarchical namespace (evaluated and rejected — [ADR-0008](docs/decisions/0008-adls-gen2-hierarchical-namespace.md)).

## Repository layout

```
terraform/    infrastructure as code (modules: storage, key_vault, function_app, event_grid, cost_guardrails, github_oidc)
functions/    deployed Azure Functions app (Python v2 model) — webhook, reconciliation, Event Grid handler, all HTTP-triggered
dbt/          dbt-duckdb transformation layer — staging → dims/fact → marts, published as Parquet
scripts/      manual/local-only operational tooling (OAuth bootstrap, backfill, mart queries) — never run in CI
mcp_server/   MCP server exposing 5 curated tools over the dbt marts, runs locally over stdio
docs/         full spec + architecture decision records
.github/      CI: infra/app deploy, dbt build/publish, external reconciliation trigger
```

See [ADR-0006](docs/decisions/0006-monorepo-layout.md) for why this is one repo, laid out by
architectural layer rather than by environment.

## Running tests

```bash
pip install -r functions/requirements-dev.txt
pytest functions/tests

pip install -r mcp_server/requirements-dev.txt
pytest mcp_server/tests
```

Both are unit tests against mocked Azure/Monzo clients or an in-memory DuckDB — nothing here
touches a real account or real infrastructure, and nothing here would catch the platform-specific
issues described above (see "A debugging story worth reading").

## Running dbt

```bash
pip install -r dbt/requirements.txt
cd dbt
DBT_PROFILES_DIR=. dbt build              # dev target: local synthetic fixtures, no cloud calls
DBT_PROFILES_DIR=. dbt build --target azure   # azure target: real Blob Storage (needs `az login`)
```

`dbt/fixtures/` holds the synthetic dataset (regenerate via `python dbt/fixtures/generate_fixtures.py`)
used for local development and CI, so PRs never need real data or Azure credentials to validate.

## Running the MCP server

```bash
pip install -r mcp_server/requirements.txt
az login   # credential_chain auth against the real marts/staging containers
python -m mcp_server.server
```

Runs over stdio - point an MCP client's config at that command rather than running it directly, or
use `scripts/query_marts.py` for one-off SQL against the same data outside an MCP client.

## Data privacy

This pipeline processes real personal financial data — `raw/`, `staging/`, and `marts/` in Blob
Storage hold my actual transaction history, not synthetic data. None of it is committed to this
repository: no real transaction data, tokens, or Azure credentials ever touch git. `.env`,
`terraform.tfstate*`, and real `*.tfvars` are gitignored, and the repo's own test/CI fixtures
(`dbt/fixtures/`) are entirely synthetic, generated data - never a copy of anything real. Nothing
in this repo is set up for anyone else's Monzo account out of the box; it's a personal instance,
published for portfolio purposes.
