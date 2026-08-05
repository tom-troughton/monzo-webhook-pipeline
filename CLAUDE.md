# monzo-de-webhook

Personal Finance Data Platform — a portfolio data engineering project ingesting Monzo transaction
data via webhook + API reconciliation, transforming it with dbt/DuckDB, and exposing curated marts
through an MCP server. Full spec: [Personal_Finance_Data_Platform_Project_Spec_v2.md](Personal_Finance_Data_Platform_Project_Spec_v2.md).

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

## Current state (update as things land)

**Built:**
- Terraform: resource group, storage account (`raw/`, `staging/`, `marts/` containers, private
  access), Storage Queue (`monzo-webhook`), Key Vault module (`terraform/modules/key_vault/`),
  Function App module (`terraform/modules/function_app/` — Consumption Linux Function App,
  Application Insights, managed-identity-only storage/Key Vault access).
- `scripts/monzo_oauth.py` — one-time interactive OAuth grant.
- `scripts/kv.py` — Key Vault helper. `scripts/monzo_auth.py` — access-token refresh (rotates the
  refresh token in Key Vault on every call). `scripts/monzo_check.py`, `scripts/monzo_transactions.py`
  — Monzo API sanity checks.

**Partially applied:** `terraform apply` for the Function App module is blocked on an Azure
subscription-level App Service quota (`Total Regional VMs` = 0, not adjustable on a Free Trial
subscription) — pending upgrade to Pay-As-You-Go, then retry.

**Not yet built:**
- Function App Python code itself (`functions/` doesn't exist yet — HTTP webhook, Queue-triggered raw
  writer, Timer-triggered reconciliation, plus `functions/shared/` per
  [ADR-0004](docs/decisions/0004-single-function-app.md)/[0007](docs/decisions/0007-oauth-bootstrap-kept-out-of-cicd.md)).
- dbt project.
- MCP server.
- GitHub Actions workflows (infra deploy, function deploy, dbt pipeline, CI).
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
