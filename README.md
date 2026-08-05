# Personal Finance Data Platform

A production-inspired data engineering platform built around my own Monzo transaction data — event-driven
ingestion, API reconciliation, incremental transformation with dbt/DuckDB, and a governed query layer
exposed over MCP. Built as a portfolio project to demonstrate patterns used in real data platforms, on a
strict personal-Azure-subscription budget.

Full spec: [docs/Personal_Finance_Data_Platform_Project_Spec_v2.md](docs/Personal_Finance_Data_Platform_Project_Spec_v2.md).
Rationale for individual design decisions: [docs/decisions/](docs/decisions/) (ADRs).

## Architecture

```text
Monzo Webhook
      │
      ▼
Azure Function (HTTP trigger) ── validate secret path + payload, enqueue, ack fast
      │
      ▼
Storage Queue ── decouples "acknowledge Monzo" from "durably persist"
      │
      ▼
Blob Storage — raw/ (immutable JSON)
      │
      ├── Timer-triggered reconciliation (Monzo API, every 6h) — source of truth,
      │   catches anything the webhook path missed
      ▼
GitHub Actions → dbt (incremental models, DuckDB as execution engine)
      │
      ▼
Blob Storage — marts/ (curated Parquet)
      │
      ▼
Python MCP Server ── curated tools only
      │
      ▼
LLM / Chat Client
```

Webhooks are treated as low-latency notifications, never as the source of truth — the scheduled
reconciliation job against the Monzo API is authoritative. See
[ADR-0001](docs/decisions/0001-reconciliation-as-source-of-truth.md).

## What this project demonstrates

- **Reliable ingestion under an unreliable delivery guarantee** — webhook + queue + reconciliation +
  idempotent writes, rather than trusting a single webhook call ([ADR-0001](docs/decisions/0001-reconciliation-as-source-of-truth.md), [ADR-0002](docs/decisions/0002-storage-queue-buffer.md)).
- **Infrastructure as code with real guardrails** — Terraform modules plus a subscription-wide Azure
  Policy module (`cost_guardrails`) that denies VM creation and restricts SKUs to non-Premium tiers,
  so a mistake can't silently produce a large bill.
- **Cost discipline as a first-class constraint**, not an afterthought — every resource choice is
  checked against Azure's always-free grants before being provisioned. See the "Cost discipline"
  section in [CLAUDE.md](CLAUDE.md).
- **Secretless CI** — GitHub Actions will authenticate to Azure via OIDC federated credentials, not a
  stored Service Principal secret ([ADR-0005](docs/decisions/0005-oidc-for-github-actions.md)).
- **A decision log, not just code** — every non-obvious architectural choice (including ones later
  reversed, like rejecting ADLS Gen2 hierarchical namespace after re-examining the justification) is
  written down with its reasoning in [docs/decisions/](docs/decisions/).

## Tech stack

Azure Functions · Azure Blob Storage · Azure Storage Queue · Azure Key Vault · Terraform · Python ·
DuckDB · dbt · GitHub Actions · MCP

## Current status

**Built:**
- Terraform: resource group, storage account (`raw/`, `staging/`, `marts/` containers), Storage Queue,
  Key Vault module, Function App module (Consumption plan, managed-identity-only access), and a
  `cost_guardrails` module enforcing subscription-wide SKU/VM policy.
- Function App code (`functions/`): HTTP webhook, queue-triggered raw writer, timer-triggered
  reconciliation, with shared Monzo auth/blob-writer/validation modules and pytest coverage
  (all mocked — no real Monzo/Azure calls in tests).
- One-time OAuth bootstrap and API sanity-check scripts (`scripts/`).

**Blocked:** `terraform apply` for the Function App is currently held up by an Azure
subscription-level App Service quota (`Y1` VMs = 0) that persists across every region tried. A
support ticket is open. Left in place deliberately as an honest snapshot rather than worked around
with a paid SKU — see the "Cost discipline" constraint in [CLAUDE.md](CLAUDE.md).

**Not yet built:** dbt project, MCP server, GitHub Actions workflows.

## Repository layout

```
terraform/    infrastructure as code (modules: storage, key_vault, function_app, cost_guardrails)
functions/    deployed Azure Functions app (Python v2 model) — webhook, queue processor, reconciliation
scripts/      manual/local-only operational tooling (OAuth bootstrap, API checks) — never run in CI
dbt/          transformation layer (not yet built)
mcp_server/   curated query layer over dbt marts (not yet built)
docs/         full spec + architecture decision records
```

See [ADR-0006](docs/decisions/0006-monorepo-layout.md) for why this is one repo, laid out by
architectural layer rather than by environment.

## Running tests

```bash
pip install -r functions/requirements-dev.txt
pytest functions/tests
```

All Function tests are unit tests against mocked Azure/Monzo clients — nothing here touches a real
account or real infrastructure.

## Data privacy

This pipeline processes real personal financial data. No real transaction data, tokens, or Azure
credentials are committed to this repository — `.env`, `terraform.tfstate*`, and real `*.tfvars` are
gitignored. Nothing in this repo is set up for anyone else's Monzo account out of the box; it's a
personal instance, published for portfolio purposes.
