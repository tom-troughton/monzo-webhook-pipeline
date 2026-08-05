# monzo-de-webhook

Personal Finance Data Platform — a portfolio data engineering project ingesting Monzo transaction
data via webhook + API reconciliation, transforming it with dbt/DuckDB, and exposing curated marts
through an MCP server. Full spec: [Personal_Finance_Data_Platform_Project_Spec_v2.md](docs/Personal_Finance_Data_Platform_Project_Spec_v2.md).

Design rationale for individual decisions lives in [docs/decisions/](docs/decisions/) as ADRs —
check there before re-deciding something that may already have a documented answer, especially
anything that looks like a strange or non-obvious choice.

## Cost discipline — always a priority

This runs on a personal Azure subscription. Zero tolerance for surprise bills; treat cost avoidance
as a standing constraint on every change, not a one-time setup decision.

- Default to Consumption/serverless SKUs (`Y1` Functions, `Standard`/`LRS` storage, etc.). Never
  Premium, dedicated, or reserved-capacity tiers unless the user explicitly asks for one and confirms
  the cost.
- Before provisioning any new resource or changing a SKU, check it fits Azure's always-free monthly
  grants or costs cents/month at most. If it doesn't, stop and say so explicitly before applying —
  don't provision first and mention cost after the fact.
- When something blocks deployment (quota limits, region restrictions, subscription-tier
  restrictions), never silently work around it by switching to a paid SKU/tier/plan. Surface the
  blocker and let the user decide how to resolve it.
- When asking for `terraform apply` confirmation, state the cost implication in plain terms, not just
  "this will create N resources."

See [docs/decisions/0003-consumption-plan-for-webhook.md](docs/decisions/0003-consumption-plan-for-webhook.md)
for the reasoning already applied to the Function App hosting plan.

## Hard constraints

- **Never commit real transaction data or secrets.** `.env`, `terraform.tfstate*`, `*.tfvars` (real,
  not `.example`) are gitignored — keep it that way. This is real personal financial data.
- **Webhooks are notifications, not the source of truth.** The Monzo API reconciliation job is
  authoritative; anything the webhook path misses gets caught there. See
  [docs/decisions/0001-reconciliation-as-source-of-truth.md](docs/decisions/0001-reconciliation-as-source-of-truth.md).
- **The Monzo OAuth bootstrap script must never run in CI.** It's an interactive, human-consent flow
  that writes the initial refresh token to Key Vault — local/manual only. See
  [docs/decisions/0007-oauth-bootstrap-kept-out-of-cicd.md](docs/decisions/0007-oauth-bootstrap-kept-out-of-cicd.md).
- **Never use `data.azurerm_client_config.current.object_id` to grant access to a specific person.**
  It resolves to whoever is *currently authenticated* - it means "me" when I run terraform locally,
  but "the GitHub Actions service principal" when CI runs the same config. Used inside a
  `for_each`/`toset`, this actually made CI destroy the human deployer's own Key Vault access when it
  ran `apply` (the set collapsed to just CI's identity from CI's point of view). Use the fixed
  `var.owner_object_id` variable instead for any permission grant meant for a specific person.

## Current state (update as things land)

**Built:**
- Terraform: resource group, storage account (`raw/`, `staging/`, `marts/` containers, private
  access), Storage Queue (`monzo-webhook`), Key Vault module (`terraform/modules/key_vault/`),
  Function App module (`terraform/modules/function_app/` — Consumption Linux Function App,
  Application Insights, managed-identity-only storage/Key Vault access), `cost_guardrails` module
  (`terraform/modules/cost_guardrails/` — subscription-wide Azure Policy: deny VM creation, restrict
  App Service Plan and Storage Account SKUs to non-Premium tiers), `github_oidc` module
  (`terraform/modules/github_oidc/` — AD app + federated credentials for master-branch pushes and
  PRs, per [ADR-0005](docs/decisions/0005-oidc-for-github-actions.md)).
- **Remote Terraform state** — Azure Blob Storage (`rg-monzode-tfstate`, AAD-RBAC auth, not account
  keys), so CI and local runs share state. The backend storage account/container are deliberately
  NOT Terraform-managed — see [ADR-0009](docs/decisions/0009-remote-state-backend.md).
- `.github/workflows/deploy.yml` — terraform plan on PRs, plan+apply on push to `master` via OIDC (no
  stored Azure secret), then `func azure functionapp publish` for the Function code. Repo variables
  `AZURE_CLIENT_ID`/`AZURE_TENANT_ID`/`AZURE_SUBSCRIPTION_ID` are set; the pipeline is verified working
  end to end (`terraform plan` and `apply` both succeed in CI) - the only remaining failure is the
  Function App's Service Plan hitting the same quota block described below, which will resolve itself
  once the ticket clears. `gh` CLI is installed and authenticated on this machine, so workflow runs can
  be inspected directly (`gh run list`, `gh run view <id> --log-failed`) instead of relying on
  copy-pasted logs.
- `functions/` — Function App code (Python v2 model, single `function_app.py`): HTTP webhook
  (validates path secret + payload, enqueues), Queue-triggered raw writer (idempotent blob naming by
  `transaction_id`), Timer-triggered reconciliation (6-hourly). Shared logic in `functions/shared/`
  (`kv.py`, `monzo_auth.py`, `blob_writer.py`, `payload_validation.py`, `transactions.py`) per
  [ADR-0004](docs/decisions/0004-single-function-app.md)/[0007](docs/decisions/0007-oauth-bootstrap-kept-out-of-cicd.md).
  Pytest coverage in `functions/tests/` (payload validation, blob idempotency, token rotation — all
  mocked, no real Monzo/Azure calls).
- `scripts/monzo_oauth.py` — one-time interactive OAuth grant, now built on `functions/shared/`.
  `scripts/monzo_check.py`, `scripts/monzo_transactions.py` — Monzo API sanity checks, same shared
  modules.
- `dbt/` — dbt-duckdb project, working end-to-end against synthetic fixtures (`dbt build` passes: 9
  models, 25 data tests). `stg_transactions` (incremental, merge on `transaction_id`, reconciliation
  wins over webhook per [ADR-0001](docs/decisions/0001-reconciliation-as-source-of-truth.md)) →
  `dim_account`/`dim_category`/`dim_merchant`/`fct_transactions` → `mart_spend_by_category`/
  `mart_monthly_cashflow`/`mart_merchant_summary`/`mart_subscriptions`, per the spec's dbt Models
  section. The `raw` source resolves via a dbt-duckdb `external_location` (`read_json_auto` over a
  `raw_transactions_glob` var) so swapping local fixtures for the real `az://.../raw/` container later
  is a one-var change, not a model rewrite. Dev profile (`dbt/profiles.yml`) uses a local, gitignored
  `dev.duckdb` file rather than `:memory:` — an in-memory database doesn't survive between separate
  `dbt` CLI invocations, which made it impossible to `dbt run` then `dbt show`/inspect afterward.
  Synthetic fixtures live in `dbt/fixtures/raw/` (regenerate via
  `python dbt/fixtures/generate_fixtures.py`), matching the exact `{"source", "transaction"}` shape
  `functions/shared/blob_writer.py` writes. No GitHub Actions workflow yet (deferred, per the spec's
  CI/CD section, until this points at real Blob Storage).

**Partially applied:** `terraform apply` for the Function App module is blocked on an Azure
subscription-level App Service quota (`Y1 VMs` / `Total Regional VMs` = 0). Self-service quota
increase failed even after upgrading to Pay-As-You-Go; a support ticket is filed and pending. Confirmed
via direct ARM API checks that the same 0-quota holds across multiple regions (uksouth, westeurope,
northeurope, eastus, swedencentral) — this is a subscription-wide review hold, not a per-region
allocation issue, so switching regions won't help.

**Not yet built:**
- dbt pipeline GitHub Actions workflow (dbt project itself now exists — see `dbt/` above — but it
  still only runs against local fixtures; wiring it to real Blob Storage and CI is deferred).
- MCP server.
- Backfill-on-demand for a specific date range (spec mentions it; not part of the 3 functions ADR-0004
  scopes, deferred).
- Hierarchical Namespace (ADLS Gen2) on the storage account — proposed, not yet enabled. See
  [docs/decisions/0008-adls-gen2-hierarchical-namespace.md](docs/decisions/0008-adls-gen2-hierarchical-namespace.md).

## Repo layout conventions

- **Monorepo, organized by architectural layer** (`terraform/`, `functions/`, `dbt/`, `mcp_server/`,
  `scripts/`), not by environment. See [docs/decisions/0006-monorepo-layout.md](docs/decisions/0006-monorepo-layout.md).
- **`scripts/`** is for manual/local-only operational tooling (OAuth bootstrap, backfills, one-off
  checks) — never invoked by CI/CD, distinct from `functions/` which is deployed runtime code.
- **One Function App, multiple triggers** (Python v2 programming model) rather than separate apps
  per trigger — shared Monzo client/auth code lives once. See
  [docs/decisions/0004-single-function-app.md](docs/decisions/0004-single-function-app.md).
- **GitHub Actions auth to Azure is OIDC federated**, not a stored Service Principal secret. See
  [docs/decisions/0005-oidc-for-github-actions.md](docs/decisions/0005-oidc-for-github-actions.md).
