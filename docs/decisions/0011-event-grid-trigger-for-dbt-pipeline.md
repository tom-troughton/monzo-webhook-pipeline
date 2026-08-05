# 0011. Event Grid trigger for the dbt pipeline

Status: Proposed
Date: 2026-08-05

## Context

The spec wants the dbt pipeline triggered by either new data landing in `raw/` (near-real-time
marts) or a nightly cron as a reliability fallback if the event path is missed. The cron fallback
is built (`.github/workflows/dbt.yml`); the event-driven path isn't.

Two things rule out the obvious implementations right now, independent of each other:

- Reacting to an Event Grid event needs *some* compute. The natural choice is a 4th trigger on the
  existing Function App, following the "one Function App, multiple triggers" pattern
  ([ADR-0004](0004-single-function-app.md)) - but that Function App can't be deployed at all right
  now, blocked on the same Azure subscription-level App Service quota described in
  [CLAUDE.md](../../CLAUDE.md)'s "Current state".
- Event Grid can't deliver directly to an arbitrary third-party webhook like GitHub's REST API.
  Webhook-type Event Grid subscriptions require the endpoint to complete a validation handshake on
  subscription creation (echo back a validation code, or be a first-party Azure delivery type that
  skips it - Function, Logic App, Storage Queue, Event Hub, Service Bus). GitHub's API doesn't
  implement that handshake, so Azure rejects creating the subscription outright. This isn't a
  workaround-able inconvenience; it's a hard constraint on the design, quota aside.

A compute-free stopgap (Event Grid → Storage Queue, with the GitHub Actions cron shortened to poll
the queue every few minutes) was considered and rejected: it would need to be thrown away and
rebuilt once the Function App exists, for the sake of shaving latency on a pipeline that already
has a working nightly fallback.

## Decision

Once the Function App quota clears, implement as:

1. An `azurerm_eventgrid_system_topic` on the storage account, with a subscription filtered to
   `Microsoft.Storage.BlobCreated` events, **subject-filtered to the `raw/` container specifically**
   (not the whole storage account). This is load-bearing, not incidental: `staging/` and `marts/`
   live on the same storage account and get rewritten by dbt every run, so a subscription scoped to
   the whole account would have the pipeline retrigger itself in a loop the moment it wrote its own
   output.
2. A new `@app.event_grid_trigger` handler in `functions/function_app.py`, alongside the existing
   HTTP/Queue/Timer triggers, that receives the blob-created event and calls GitHub's
   `POST /repos/{owner}/{repo}/dispatches` API with `event_type: raw-data-updated`.
3. `.github/workflows/dbt.yml` gains a `repository_dispatch: types: [raw-data-updated]` trigger
   alongside the existing `push`/`schedule`/`workflow_dispatch` ones, running the same `publish` job
   the cron path already uses - no new job, no new dbt logic.
4. Calling GitHub's API needs a GitHub token. Store it in Key Vault as
   `github-dispatch-token`, following the exact pattern the Monzo secrets already use, scoped as
   narrowly as GitHub allows for triggering `repository_dispatch` on a single repo (verify the
   minimal permission at implementation time - a fine-grained PAT limited to this repo is the
   target, not a classic PAT with broad `repo` scope). The Function App's managed identity already
   has `Key Vault Secrets User` on the whole vault, so no new RBAC grant is needed to read it.

Accepting a stored GitHub token here is a deliberate, scoped exception to
[ADR-0005](0005-oidc-for-github-actions.md)'s secretless-CI principle. That ADR covers GitHub
Actions authenticating *to* Azure, where OIDC federation is available. This is the reverse
direction - Azure calling GitHub's REST API - and no OIDC equivalent exists for it.

## Consequences

- One more secret to provision and rotate, where every other credential in this project is either
  OIDC-federated or a Monzo-issued token already going through Key Vault. Worth it for the
  near-real-time behavior the spec asks for; the scope should stay as narrow as GitHub allows.
- The nightly cron and manual `workflow_dispatch` triggers stay in place regardless - Event Grid is
  additive (the near-real-time path), not a replacement for the reliability fallback.
- Blocked until the Function App itself can be deployed, so this stays `Proposed` rather than
  `Accepted`. Revisit once the quota ticket clears.
- If GitHub's dispatch API or auth model changes before this is built, the subject-filter-scoping
  reasoning (point 1 above) still applies to whatever destination replaces the Function - re-check
  it rather than assuming it's specific to this exact implementation.
