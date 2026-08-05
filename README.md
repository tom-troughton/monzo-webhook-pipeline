# Personal Finance Data Platform

A production-inspired data engineering platform built around my own Monzo transaction data — event-driven
ingestion, API reconciliation, incremental transformation with dbt/DuckDB, and a governed query layer
exposed over MCP. Built as a portfolio project to demonstrate patterns used in real data platforms, on a
strict personal-Azure-subscription budget.

Full spec: [docs/Personal_Finance_Data_Platform_Project_Spec_v2.md](docs/Personal_Finance_Data_Platform_Project_Spec_v2.md).
Rationale for individual design decisions: [docs/decisions/](docs/decisions/) (ADRs).

## Architecture

```text
Monzo Webhook                          Monzo API
      │                                     │
      ▼                                     │ (not yet deployed - blocked on
Azure Function (HTTP trigger)               │  Function App quota; scripts/
  validate secret path + payload,           │  backfill_transactions.py fills
  enqueue, ack fast                         │  in manually for now)
      │                                     │
      ▼                                     │
Storage Queue                               │
  decouples "acknowledge Monzo"             │
  from "durably persist"                    │
      │                                     │
      ▼                                     ▼
            Blob Storage — raw/ (immutable JSON)
                          │
                          ▼
       GitHub Actions → dbt (incremental models,
              DuckDB as execution engine)
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
[ADR-0001](docs/decisions/0001-reconciliation-as-source-of-truth.md). Until that Function is
deployed, `raw/` is populated by a one-off manual backfill script instead (same underlying write
path the Function will eventually use) — see "Current status" below.

## What this project demonstrates

- **Reliable ingestion under an unreliable delivery guarantee** — webhook + queue + reconciliation +
  idempotent writes, rather than trusting a single webhook call ([ADR-0001](docs/decisions/0001-reconciliation-as-source-of-truth.md), [ADR-0002](docs/decisions/0002-storage-queue-buffer.md)).
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
  ([ADR-0005](docs/decisions/0005-oidc-for-github-actions.md)).
- **Designing for real data, not just the happy path** — real Monzo API responses immediately broke
  assumptions synthetic test fixtures had masked (optional fields omitted rather than sent as
  `null`, empty-string sentinels instead of `null`, an unanticipated category value) - the dbt
  layer now declares an explicit schema instead of relying on inference, and a taxonomy-drift test
  warns instead of hard-failing the pipeline. See the dbt bullet in [CLAUDE.md](CLAUDE.md)'s
  "Current state" for the specifics.
- **A decision log, not just code** — every non-obvious architectural choice (including ones later
  reversed, like rejecting ADLS Gen2 hierarchical namespace after re-examining the justification) is
  written down with its reasoning in [docs/decisions/](docs/decisions/).

## Tech stack

Azure Functions · Azure Blob Storage · Azure Storage Queue · Azure Key Vault · Terraform · Python ·
DuckDB · dbt · GitHub Actions · MCP

## Current status

**Built:**
- **Infrastructure** (`terraform/`): resource group, storage account (`raw/`, `staging/`, `marts/`
  containers, RBAC least-privileged per identity — see [CLAUDE.md](CLAUDE.md) for the exact grants),
  Storage Queue, Key Vault module, Function App module (Consumption plan, managed-identity-only
  access), `cost_guardrails` (subscription-wide Azure Policy: no VMs, no Premium SKUs), and
  `github_oidc` (federated credentials, no stored Azure secret).
- **Function App code** (`functions/`): HTTP webhook, queue-triggered raw writer, timer-triggered
  reconciliation, with shared Monzo auth/blob-writer/validation modules and pytest coverage
  (all mocked — no real Monzo/Azure calls in tests). Not deployed yet — see "Blocked" below.
- **dbt project** (`dbt/`), verified end-to-end against both local synthetic fixtures and real Blob
  Storage: `stg_transactions` (incremental, dedupes webhook vs. reconciliation sources) →
  dimension/fact models → 4 curated marts, materialized straight to Parquet in `staging/`/`marts/`.
  Two targets - `dev` (local fixtures, no cloud calls) and `azure` (the real containers, via
  DuckDB's `azure` extension with OIDC/`credential_chain` auth, no stored secret).
- **`.github/workflows/`**: `deploy.yml` (Terraform plan/apply + Function publish, OIDC) and
  `dbt.yml` (dbt build against fixtures on every PR, against real Blob Storage on push to
  `master`/nightly cron/manual dispatch).
- **`raw/`/`staging/`/`marts/` hold my real transaction history**, not synthetic data —
  `scripts/backfill_transactions.py` pulled it via the Monzo API (manual, one-off, ahead of the
  reconciliation Function being deployed) using the exact same write path that Function will
  eventually use.
- **Operational scripts** (`scripts/`): one-time OAuth bootstrap, API sanity checks, the backfill
  above, and `query_marts.py` for ad-hoc SQL against the real marts.
- **MCP server** (`mcp_server/`): the 5 curated tools the spec names — `get_spend_by_category`,
  `get_monthly_cashflow`, `get_top_merchants`, `get_subscriptions`, `get_data_quality_report` — over
  the same marts, plus pytest coverage against an in-memory DuckDB (no real Azure access needed to
  run the tests). Runs locally/on-demand over stdio (`python -m mcp_server.server`), not hosted, per
  the spec's intent.

**Blocked:** `terraform apply` for the Function App is currently held up by an Azure
subscription-level App Service quota (`Y1` VMs = 0) that persists across every region tried. A
support ticket is open. Left in place deliberately as an honest snapshot rather than worked around
with a paid SKU — see the "Cost discipline" constraint in [CLAUDE.md](CLAUDE.md). This is also why
`raw/` is populated by a manual backfill script for now rather than the webhook/reconciliation path.

**Not yet built:** the Event Grid (blob-created) trigger for near-real-time dbt runs (currently
push/cron/manual only — see [ADR-0011](docs/decisions/0011-event-grid-trigger-for-dbt-pipeline.md)
for why, and the design once the Function App quota clears), dbt docs hosting (generated in CI,
just not hosted anywhere yet).

## Repository layout

```
terraform/    infrastructure as code (modules: storage, key_vault, function_app, cost_guardrails, github_oidc)
functions/    deployed Azure Functions app (Python v2 model) — webhook, queue processor, reconciliation
dbt/          dbt-duckdb transformation layer — staging → dims/fact → marts, published as Parquet
scripts/      manual/local-only operational tooling (OAuth bootstrap, backfill, mart queries) — never run in CI
mcp_server/   MCP server exposing 5 curated tools over the dbt marts, runs locally over stdio
docs/         full spec + architecture decision records
.github/      CI: infra/app deploy, dbt build/publish
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
touches a real account or real infrastructure.

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
