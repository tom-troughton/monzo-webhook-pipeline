# monzo-de-webhook

Personal Finance Data Platform — a portfolio data engineering project ingesting Monzo transaction
data via webhook + API reconciliation, transforming it with dbt/DuckDB, and exposing curated marts
through an MCP server. Full spec: [Personal_Finance_Data_Platform_Project_Spec_v2.md](Personal_Finance_Data_Platform_Project_Spec_v2.md).

Design rationale for individual decisions lives in [docs/decisions/](docs/decisions/) as ADRs —
check there before re-deciding something that may already have a documented answer, especially
anything that looks like a strange or non-obvious choice.

## Hard constraints

- **Azure free tier.** No Premium/always-on plans, no resources with standing monthly cost beyond
  cents. See [docs/decisions/0003-consumption-plan-for-webhook.md](docs/decisions/0003-consumption-plan-for-webhook.md).
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
  access), Key Vault module (`terraform/modules/key_vault/`).
- `scripts/monzo_oauth.py` — one-time interactive OAuth grant.
- `scripts/kv.py`, `scripts/monzo_check.py` — Key Vault helper / Monzo API sanity check.

**Not yet built:**
- Azure Function App (HTTP webhook + Queue trigger + Timer-triggered reconciliation).
- Storage Queue between webhook and raw blob write.
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
