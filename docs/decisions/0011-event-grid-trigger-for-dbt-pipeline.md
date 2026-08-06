# 0011. Event Grid trigger for the dbt pipeline

Status: Accepted
Date: 2026-08-05 (implemented 2026-08-06)

## Context

The spec wants the dbt pipeline triggered by either new data landing in `raw/` (near-real-time
marts) or a nightly cron as a reliability fallback if the event path is missed. The cron fallback
is built (`.github/workflows/dbt.yml`); the event-driven path wasn't, blocked on two things
independent of each other:

- Reacting to an Event Grid event needs *some* compute. The natural choice was a 4th trigger on the
  existing Function App, following the "one Function App, multiple triggers" pattern
  ([ADR-0004](0004-single-function-app.md)) - but the Function App couldn't be deployed at all at
  the time, blocked on the `Y1` quota issue ([ADR-0012](0012-flex-consumption-hosting-plan.md)
  resolved this separately).
- Event Grid can't deliver directly to an arbitrary third-party webhook like GitHub's REST API.
  Webhook-type Event Grid subscriptions require the endpoint to complete a validation handshake on
  subscription creation (echo back a validation code, or be a first-party Azure delivery type that
  skips it - Function, Logic App, Storage Queue, Event Hub, Service Bus). GitHub's API doesn't
  implement that handshake, so Azure rejects creating the subscription outright.

## Decision

1. An `azurerm_eventgrid_system_topic` on the storage account, with a subscription filtered to
   `Microsoft.Storage.BlobCreated` events, **subject-filtered to the `raw/` container specifically**
   (not the whole storage account). This is load-bearing, not incidental: `staging/` and `marts/`
   live on the same storage account and get rewritten by dbt every run, so a subscription scoped to
   the whole account would have the pipeline retrigger itself in a loop the moment it wrote its own
   output.
2. The subscription delivers to a **Storage Queue** (`raw-data-events`), not directly to the
   Function App - see "Rejected: azure_function_endpoint" below for why. A
   `@app.queue_trigger` handler in `functions/function_app.py`, alongside the existing
   HTTP/Queue/Timer triggers, consumes it and calls GitHub's `POST /repos/{owner}/{repo}/dispatches`
   API with `event_type: raw-data-updated`. The queue message content (a Storage BlobCreated event)
   is never inspected - arrival alone is the signal, since the subject filter already did the
   relevant filtering upstream.
3. `.github/workflows/dbt.yml` gains a `repository_dispatch: types: [raw-data-updated]` trigger
   alongside the existing `push`/`schedule`/`workflow_dispatch` ones, running the same `publish` job
   the cron path already uses - no new job, no new dbt logic.
4. Calling GitHub's API needs a GitHub token. Stored in Key Vault as `github-dispatch-token`,
   following the exact pattern the Monzo secrets already use - a fine-grained PAT limited to this
   repo, `Contents: Read and write` only. The Function App's managed identity already has
   `Key Vault Secrets User` on the whole vault, so no new RBAC grant was needed to read it.

Accepting a stored GitHub token here is a deliberate, scoped exception to
[ADR-0005](0005-oidc-for-github-actions.md)'s secretless-CI principle. That ADR covers GitHub
Actions authenticating *to* Azure, where OIDC federation is available. This is the reverse
direction - Azure calling GitHub's REST API - and no OIDC equivalent exists for it.

## Rejected: `azure_function_endpoint` destination (confirmed Azure platform bug)

The first implementation attempt delivered directly to the Function via
`azurerm_eventgrid_system_topic_event_subscription`'s `azure_function_endpoint` block - the more
"native" design, no extra queue resource needed. It consistently failed:

```
Endpoint validation: Destination endpoint not found. Resource details: resourceId: .../functions/on_raw_data_created.
Resource should pre-exist before attempting this operation.
```

This looked at first like an ordinary bootstrap-ordering problem (the subscription can't reference a
function that isn't deployed yet), and the function *was* deployed and confirmed correctly indexed
- via `az functionapp function list`, via a direct ARM GET on the function's resource ID (which
returned it correctly typed as `eventGridTrigger`), and by retrying across a 19+ minute span
including a full research detour. It failed identically every time regardless.

To rule out a Terraform/provider-specific cause, the same subscription was attempted by hand through
the Azure Portal - the official first-party UI, no Terraform involved. It failed with the exact same
error. That's decisive: this is a genuine Azure platform bug/limitation in how Flex Consumption
function endpoints interact with Event Grid's endpoint-validation step, not anything wrong in this
project's config or the `azurerm` provider.

Switched to the Storage Queue destination instead, which worked on the first attempt (subscription
created in 13 seconds). Storage Queues don't go through whatever extra function-discovery layer the
`azure_function_endpoint` validation depends on - the queue is visible to Event Grid the instant
Terraform creates it, no separate indexing step to race against.

## Consequences

- One more secret to provision and rotate, where every other credential in this project is either
  OIDC-federated or a Monzo-issued token already going through Key Vault. Worth it for the
  near-real-time behavior the spec asks for; the scope stays as narrow as GitHub allows.
- The nightly cron and manual `workflow_dispatch` triggers stay in place regardless - Event Grid is
  additive (the near-real-time path), not a replacement for the reliability fallback.
- One more moving part than the direct-to-Function design would have been (a queue resource, plus
  the Function consuming from it rather than being invoked directly) - accepted because the simpler
  design doesn't currently work, not by choice.
- If Microsoft fixes the underlying `azure_function_endpoint` + Flex Consumption bug later, there's
  no pressing need to migrate back - the Storage Queue path works and isn't meaningfully worse.
- Also surfaced and fixed along the way, unrelated to the above: a persistent
  `site_config.application_insights_connection_string` drift on `azurerm_function_app_flex_consumption`
  (Azure reflects the app_settings value back onto that attribute after every deploy; Terraform's
  config had no opinion on it, so every `apply` "fixed" it back to null, causing a real Function App
  restart on every single apply). Fixed with a `lifecycle { ignore_changes = [...] }` in
  `terraform/modules/function_app/main.tf`.
