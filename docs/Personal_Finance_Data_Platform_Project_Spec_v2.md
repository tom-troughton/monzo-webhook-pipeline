# Personal Finance Data Platform – Project Specification (v2)

## Objective

Build a production-inspired end-to-end data platform around personal Monzo transaction data, demonstrating modern data engineering practices: event-driven ingestion, reconciliation against a source system, incremental transformation, data quality testing, and a governed query interface via MCP.

## High-Level Architecture

```text
Monzo Webhook
      │
      ▼
Azure Function (HTTP Trigger)
      │  validate secret path + payload shape
      │  persist raw payload
      │  return HTTP 200 immediately
      ▼
Storage Queue (buffer)
      │
      ▼
Azure Blob Storage (raw JSON, immutable)
      │
      ├── Scheduled reconciliation job (Timer-triggered Function → Monzo API)
      │      - refreshes OAuth token via Key Vault-stored refresh token
      │      - backfills missed/duplicate-checked transactions
      ▼
Event Grid (blob created) ──or── nightly cron
      │
      ▼
GitHub Actions (dbt pipeline)
      │
      ├── dbt deps
      ├── dbt run (incremental models, watermarked)
      ├── dbt test
      └── dbt docs generate
      ▼
Blob Storage (analytics marts - partitioned Parquet)
      │
      ▼
Python MCP Server (local/on-demand)
      │
      ▼
LLM / Chat Client

Separate pipeline: GitHub Actions (infra/app deploy)
      │
      ├── terraform plan / apply   (OIDC federated auth, no stored secrets)
      └── func azure functionapp publish
```

## Technology Stack

- Azure Functions (HTTP trigger + Timer trigger)
- Azure Storage Queue
- Azure Blob Storage
- Azure Event Grid (blob-created trigger, optional over cron)
- Terraform
- Python
- DuckDB
- dbt (dbt-duckdb adapter)
- GitHub Actions (OIDC federated identity)
- Docker
- MCP

## Terraform

Provision:
- Resource Group
- Storage Account
- Blob containers (`raw/`, `staging/`, `marts/`)
- Storage Queue (webhook buffer)
- Function App (HTTP-triggered webhook, Timer-triggered reconciliation)
- Application Insights
- Key Vault (Monzo client secret, refresh token, webhook path secret)
- Managed Identity (Function App → Key Vault, Function App → Storage)
- Federated credential for GitHub Actions OIDC (no long-lived Service Principal secrets)
- RBAC (least-privilege role assignments per identity/container)

Use modules for storage, function app, monitoring and security. Use Terraform workspaces (or separate state) for `dev` and `prod` so infra changes can be tested before touching the real webhook endpoint.

## Ingestion

### Webhook

Responsibilities:
- Validate the request:
  - Monzo does **not** sign webhook payloads (no HMAC), so validation means: the URL path/query includes an unguessable secret stored in Key Vault, and the payload is checked against the expected Monzo transaction schema before being trusted.
  - Reject anything that doesn't match the secret or schema with a 4xx, without persisting it.
- Persist the raw payload to the Storage Queue (not directly to Blob) so the Function can return fast and a separate process handles the write.
- Return HTTP 200 immediately (target < 1s to avoid Monzo retry storms; see Hosting Plan below).

Do not perform transformations in the webhook.

### Queue

A Storage Queue sits between the HTTP-triggered Function and the raw Blob write. This decouples "acknowledge Monzo" from "durably persist," so a transient Blob Storage error doesn't cause a dropped webhook, and the ingestion Function can stay minimal. A Queue-triggered Function consumes messages and writes to `raw/`.

### Reconciliation

Treat webhooks as notifications, not the source of truth.

Implement:
- Idempotency using `transaction_id` (webhook-sourced and reconciliation-sourced raw records must dedupe on this key downstream).
- Scheduled reconciliation (Timer-triggered Function, e.g. every 6 hours) that pulls recent transactions from the Monzo API and writes any missing ones to `raw/`.
- Duplicate detection at the staging layer (dbt), not at ingestion — raw stays append-only and untouched.
- Backfill of missing transactions on demand (manual trigger for a date range).

### Monzo OAuth token lifecycle

Monzo access tokens are short-lived and personal access tokens issued via the developer playground expire after a few hours unless the app is a properly registered confidential client with refresh tokens. The reconciliation job depends on a valid token, so:
- Register a proper OAuth client (not a playground token) so refresh tokens are available.
- Store `client_id`, `client_secret`, and the current `refresh_token` in Key Vault.
- On each reconciliation run, refresh the access token first, then use it; write the new `refresh_token` back to Key Vault (Monzo rotates it on use).
- Alert (Application Insights) if token refresh fails — this is the most likely silent-failure point in the whole pipeline.

## Storage

```
raw/
  YYYY/MM/DD/*.json          # immutable, append-only, one file per ingested event

staging/
  YYYY/MM/transactions.parquet   # partitioned by month, incremental dbt model

marts/
  spend_by_category.parquet
  merchant_summary.parquet
  monthly_cashflow.parquet
  subscriptions.parquet
```

Raw data is immutable. Staging is partitioned (not a single monolithic file) so dbt can run incremental merges scoped to affected partitions instead of rewriting the whole dataset on every run.

## Transformations

GitHub Actions orchestrates dbt, triggered by either:
- Event Grid → repository dispatch when new files land in `raw/`, for near-real-time marts, or
- A nightly cron schedule as a reliability fallback if the event path is missed.

Workflow:
1. Checkout repository
2. Authenticate to Azure via OIDC (federated credential, no stored secret)
3. Install dependencies
4. Read new raw JSON from Blob Storage (watermarked by last-processed timestamp/partition)
5. Run dbt (`stg_transactions` as an incremental model keyed on `transaction_id`, deduping webhook vs. reconciliation sources)
6. Run dbt tests
7. Generate docs
8. Write mart Parquet files back to Blob Storage

DuckDB is used purely as the execution engine. No persistent DuckDB database file is required.

## dbt Models

Staging:
- `stg_transactions` (incremental, unique on `transaction_id`, sourced from raw JSON)

Dimensions:
- `dim_account`
- `dim_category`
- `dim_merchant`

Facts:
- `fct_transactions`

Marts:
- `mart_spend_by_category`
- `mart_monthly_cashflow`
- `mart_merchant_summary`
- `mart_subscriptions`

## Data Quality

- Unique transaction IDs
- Not-null tests on required fields
- Accepted values (e.g. currency, transaction type)
- Freshness checks (alert if no new raw data in N hours — catches both a dead webhook and a stuck reconciliation job)
- Reconciliation checks (row counts / sums between raw and staging, and between Monzo API totals and warehouse totals)

## Security & Secrets

- All secrets (Monzo client secret, refresh token, webhook path secret) live in Key Vault, never in code or GitHub Actions secrets.
- Function App uses a Managed Identity to read Key Vault and read/write Blob Storage — no connection strings in app settings.
- GitHub Actions authenticates to Azure via OIDC federated credentials scoped to this repo/branch — no stored Service Principal secret.
- RBAC grants are least-privilege and container-scoped (e.g. the dbt pipeline identity can read `raw/`+`staging/` and write `marts/`, but not delete `raw/`).

## Data Privacy & Handling

This pipeline processes real personal financial data. Treat it accordingly:
- Never commit real transaction data, raw JSON samples, or Blob Storage emulator output to git — `.gitignore` local emulator/data directories explicitly.
- Use synthetic/anonymized transaction data for any fixtures, tests, screenshots, or portfolio write-ups.
- Storage Account should have public blob access disabled and encryption at rest (default for Azure Storage) confirmed in Terraform.
- Consider a data retention policy for `raw/` (e.g. lifecycle rule to move older raw JSON to cool/archive tier) — not required for correctness, but realistic for a "production-inspired" platform.

## Hosting Plan

Use an Azure Functions **Premium** (or at minimum, a pinged/warm Consumption) plan for the HTTP-triggered webhook Function specifically, since Monzo expects a fast acknowledgement and Consumption-plan cold starts risk missed/retried webhook deliveries. The Timer-triggered reconciliation Function is not latency-sensitive and can run on Consumption regardless.

## CI/CD Pipelines

Two separate GitHub Actions workflows:
1. **Infra/app deploy** — `terraform plan`/`apply` on infra changes, `func azure functionapp publish` on Function code changes. Gated behind manual approval for `prod`.
2. **dbt pipeline** — as described in Transformations, triggered by new raw data or nightly cron.

Keeping these separate avoids an unrelated dbt model change triggering an infra apply, and vice versa.

## Testing Strategy

- **dbt tests** cover the warehouse layer (uniqueness, not-null, accepted values, freshness, reconciliation).
- **Python unit tests** (pytest) for the Function code: webhook payload validation, queue message handling, token refresh logic — mocked against the Monzo API and Azure SDKs, not hitting real services.
- **Terraform validation** (`terraform validate`, `terraform plan` in CI) before apply.

## MCP

Expose curated tools only:
- `get_spend_by_category`
- `get_monthly_cashflow`
- `get_top_merchants`
- `get_subscriptions`
- `get_data_quality_report`

MCP queries curated dbt marts using DuckDB. Runs locally/on-demand rather than as a hosted service, since this is a personal-use portfolio tool rather than a multi-tenant product.

## Observability

- Application Insights on both Functions (webhook + reconciliation), with structured logging (transaction ID, source: webhook/reconciliation, outcome).
- Alert rules for: token refresh failure, webhook validation failures spiking (possible probing), and dbt freshness test failures.

## Future Enhancements

- Spending anomaly detection
- Budget forecasting
- dbt docs hosting
- Monitoring dashboard (Grafana/Azure Workbook over Application Insights + data quality results)
- Multi-account support (joint/business accounts)

## Design Decisions

- Azure for depth of experience.
- Terraform for Infrastructure as Code, with OIDC over stored secrets for CI auth.
- DuckDB as compute engine over Parquet — no persistent DB file, keeps GitHub Actions runners stateless.
- dbt for modelling, testing and documentation; incremental models over full-refresh to avoid rewriting all historical data on every run.
- GitHub Actions for low-cost orchestration, split into infra-deploy and dbt-pipeline workflows.
- Storage Queue between webhook and raw persistence to decouple "acknowledge Monzo" from "durably write," reducing dropped-webhook risk without needing a heavier message broker.
- Webhooks treated as notifications only; reconciliation against the Monzo API is the source of truth, since Monzo does not guarantee webhook delivery.
- Docker for reproducible environments.
- No Kubernetes because workload does not justify it.
