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
  modules. `scripts/backfill_transactions.py` — one-off full-history backfill into `raw/` (see
  below). `scripts/query_marts.py` — queries the real `marts/*.parquet` files straight from Blob
  Storage (own bare `duckdb.connect()` + `credential_chain` secret, independent of the dbt
  project's connection) - no-arg prints all 4 marts, or pass a SQL string to run your own query
  against them (they're pre-registered as views named after the mart, e.g. `subscriptions`).
  Stopgap for the not-yet-built MCP server, which will expose curated versions of these same
  queries as tools instead of raw SQL.
- `dbt/` — dbt-duckdb project, verified end-to-end against both local fixtures and the real `raw/`
  container (`dbt build` passes: 10 models, 25 data tests, either way). `stg_transactions`
  (incremental, merge on `transaction_id`, reconciliation wins over webhook per
  [ADR-0001](docs/decisions/0001-reconciliation-as-source-of-truth.md)) →
  `dim_account`/`dim_category`/`dim_merchant`/`fct_transactions` → `mart_spend_by_category`/
  `mart_monthly_cashflow`/`mart_merchant_summary`/`mart_subscriptions`, per the spec's dbt Models
  section. Two dbt targets (`dbt/profiles.yml`): `dev` (default) reads local synthetic fixtures
  (`dbt/fixtures/raw/`, regenerate via `python dbt/fixtures/generate_fixtures.py`), no Azure auth;
  `azure` reads the real `raw/` container via the DuckDB `azure` extension with `credential_chain`
  auth — no stored secret, resolves through `az login` locally. **`raw/`/`staging/`/`marts/` hold
  real transaction data now, not synthetic** — `scripts/backfill_transactions.py` (manual/local
  only, mirrors `functions/shared/transactions.py`'s pagination but pulls full history, not just
  24h) pulled real transactions via the Monzo API and wrote them with the same
  `write_transaction()` the reconciliation Function will eventually use, after the earlier
  synthetic blobs were deleted (`az storage blob delete-batch`). Real API responses immediately
  exposed two things the synthetic fixtures hadn't: (1) Monzo omits optional fields like
  `decline_reason` entirely rather than sending `null` when absent, which breaks
  `read_json_auto`'s union-by-name schema inference the moment a batch has no file with that key
  set — `_sources.yml`'s `external_location` now declares an explicit `read_json(..., columns=
  {...})` schema instead, so every column always exists; (2) Monzo sends `settled` as `""`, not
  `null`, for unsettled transactions - `stg_transactions.sql` now does
  `nullif(transaction.settled, '')::timestamp`. Also surfaced a real category value
  (`savings`) the accepted_values test's hand-picked list didn't have — that test is now
  `severity: warn` rather than error, since Monzo's category taxonomy is external and evolving,
  not something a hard pipeline failure should gate on.
- **`staging/` and `marts/` are now real dbt outputs, not just provisioned containers.** The 4
  `mart_*` models are materialized `external` (DuckDB `COPY ... TO ... FORMAT PARQUET`), writing
  the exact filenames the spec's Storage section names (`marts/spend_by_category.parquet`, etc,
  not `mart_spend_by_category.parquet`). `stg_transactions` itself stays `incremental`/in-catalog
  (its merge logic needs that); a thin sibling model, `export_staging_transactions`, republishes
  its current contents to `staging/` as Parquet Hive-partitioned by `transaction_year`/
  `transaction_month` — a separate model because dbt-duckdb's `external` materialization always
  does a full rewrite and can't also be `incremental`. `options: {overwrite_or_ignore: 'true'}`
  keeps partitioned reruns idempotent (DuckDB errors on rerun into an existing partition dir
  without it). Where each writes to is resolved by the `blob_location()` macro
  (`dbt/macros/blob_location.sql`): local `export/{container}/` folder for `dev`, real
  `az://{container}/` for `azure` — same `target.name` check as the source, for the same reason
  (see gotcha below). The `dev` target's `export/` output dir must exist before running (DuckDB
  doesn't auto-create write directories) — `dbt/export/` is gitignored, not a fixture; the CI
  workflow `mkdir -p`s it before `dbt build`.
  **Gotcha:** dbt does *not* re-render Jinja inside `vars:` values in `dbt_project.yml` — a var set
  to `"{{ 'x' if target.name == ... }}"` is passed through literally, not evaluated. Both the
  `dev`/`azure` source-path switch (`models/staging/_sources.yml`'s `external_location`) and the
  output-path switch (`blob_location()` macro) had to be plain Jinja in a model/macro context
  (where `target.name` does resolve), not a project-level var.
  **Gotcha #2:** custom macros aren't available either, specifically inside a source's
  `external_location` — dbt-duckdb renders that during project *parsing* (building the manifest),
  before custom macros are registered, so `{{ my_macro() }}` there fails with `'my_macro' is
  undefined` even though the same macro works fine from any model. `_sources.yml`'s
  `external_location` is one long inlined expression because of this, not a call to a macro.
  **Gotcha #3:** dbt-duckdb's default (`newstyle`) formatter runs `external_location` through
  Python's `str.format_map()` after Jinja rendering — a `columns={...}` map (needed for gotcha #1
  above) has literal braces that collide with `.format_map()`'s substitution syntax and throw a
  `KeyError`. Doubling the braces doesn't work either: Jinja renders first and would evaluate the
  doubled braces as its own dict-literal expression, undoing the escaping. Fix: set
  `meta.formatter: oldstyle` on the source, which uses `%`-substitution instead — a string with no
  `%` in it just passes through unchanged.
  Also: each target uses its own local DuckDB file (`dev.duckdb`/`azure.duckdb`, gitignored) rather
  than `:memory:`, since an in-memory DB doesn't survive between separate `dbt` CLI invocations
  (breaks `dbt run` then `dbt show`), and a shared file would mix tables from both sources.
- Reading the storage account's **data plane** needed an explicit RBAC grant even for the
  subscription owner — `Contributor` at the resource-group scope only covers control-plane
  operations, same gotcha the tfstate backend already required a workaround for. `terraform/main.tf`
  grants the owner `Storage Blob Data Contributor` on the whole storage account. GitHub Actions OIDC
  gets the same role but container-scoped per the spec's least-privilege intent: `Storage Blob Data
  Reader` on `raw/` only, `Storage Blob Data Contributor` on `staging/` and `marts/` (needs to write
  there, but still can't touch/delete `raw/`).
- `.github/workflows/dbt.yml` — two jobs: `build` runs `dbt build` against the `dev` target (local
  fixtures, no Azure auth) on every PR/push touching `dbt/**`, so a broken model/test fails fast
  without touching real data; `publish` (push to `master`, nightly cron at 05:00 UTC as the
  spec's reliability fallback since the Event Grid "new raw data" trigger isn't built, or manual
  `workflow_dispatch`) runs `dbt build --target azure` against real Blob Storage via the same
  `azure/login@v2` OIDC pattern `deploy.yml` uses — the action performs an actual `az login` with
  the federated token, which is what lets DuckDB's `credential_chain` (`chain: cli`) authenticate
  in CI exactly like it does locally. Also runs `dbt docs generate` and uploads the docs as a build
  artifact (7-day retention) — not hosted anywhere yet, just downloadable for now.

**Partially applied:** `terraform apply` for the Function App module is blocked on an Azure
subscription-level App Service quota (`Y1 VMs` / `Total Regional VMs` = 0). Self-service quota
increase failed even after upgrading to Pay-As-You-Go; a support ticket is filed and pending. Confirmed
via direct ARM API checks that the same 0-quota holds across multiple regions (uksouth, westeurope,
northeurope, eastus, swedencentral) — this is a subscription-wide review hold, not a per-region
allocation issue, so switching regions won't help.

**Not yet built:**
- MCP server.
- Event Grid (blob-created) trigger for the dbt pipeline — currently push-to-master/nightly
  cron/manual only (`.github/workflows/dbt.yml`), per the spec's fallback path; the near-real-time
  event-driven path is deferred. **Deliberately left blocked on the Function App quota, not
  worked around:** the spec's design needs *some* compute to react to the Event Grid event and
  call GitHub's `repository_dispatch` API — the natural choice is a 4th trigger on the existing
  Function App, which is blocked by the exact same quota. A direct Event Grid → GitHub webhook
  isn't viable either: Event Grid requires webhook endpoints to complete a validation handshake on
  subscription creation, and GitHub's API doesn't implement it, so Azure rejects creating that
  subscription outright, quota aside. A compute-free stopgap (Event Grid → Storage Queue, short-
  interval CI polling) was considered and explicitly rejected — not worth building something that
  would just get thrown away once the Function App exists.
- dbt docs hosting (currently just uploaded as a downloadable CI artifact, per the spec's Future
  Enhancements section).
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
