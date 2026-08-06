# 0015. Switch the Event Grid destination from a Storage Queue to a webhook endpoint

Status: Accepted
Date: 2026-08-06

## Context

[ADR-0011](0011-event-grid-trigger-for-dbt-pipeline.md) settled on Event Grid delivering to a
Storage Queue (`raw-data-events`), consumed by `on_raw_data_created` via `@app.queue_trigger`, after
the original `azure_function_endpoint` design hit a confirmed Azure platform bug.

After [ADR-0013](0013-externally-triggered-reconciliation.md) fixed `reconcile`'s equivalent
problem (Timer triggers not waking a scaled-to-zero Flex Consumption app), the same class of issue
turned up here too. Verified directly: after reconciliation wrote 4 real transactions to `raw/`,
Event Grid's own metrics confirmed `PublishSuccessCount`, `MatchedEventCount`, and
`DeliverySuccessCount` all at 4 - Event Grid did its job correctly and the messages were sitting in
the queue. But `on_raw_data_created` never fired, across 12+ minutes of polling, even after forcing
the app awake with an unrelated HTTP call. Web research confirmed this is the same documented
limitation: "a queue-triggered function may not automatically start unless there's an always-ready
instance" - queue triggers, not just timer triggers, need a running host to poll, and Flex
Consumption's scale-to-zero doesn't reliably provide one.

Unlike `reconcile`, driving this externally via GitHub Actions polling wasn't the right fix - that
would reintroduce the polling latency Event Grid exists to avoid, essentially rebuilding the
"compute-free stopgap" ADR-0011 already rejected. HTTP triggers, by contrast, have now proven
reliable on this app every time (`webhook`, `reconcile`) - external callers force a cold start Azure
Functions' front door can always route to, unlike the internal scale-controller polling that Timer
and Queue triggers depend on.

## Decision

Convert `on_raw_data_created` to an HTTP route (`on_raw_data_created/{path_secret}`, same
path-secret pattern as `webhook`/`reconcile`, new dedicated secret `event-grid-trigger-secret`) and
switch the Event Grid subscription's destination from `storage_queue_endpoint` to `webhook_endpoint`.

Generic Webhook destinations (unlike the first-party `azure_function_endpoint`, Storage Queue, Event
Hub, etc. types) require completing Event Grid's subscription-validation handshake: on subscription
creation, Event Grid POSTs a `Microsoft.EventGrid.SubscriptionValidationEvent` containing a
`validationCode`, and the endpoint must echo it back as `{"validationResponse": ...}` for the
subscription to be confirmed. Implemented in `functions/shared/event_grid.py`.

Deployed the updated function code *before* applying the Terraform change this time, having learned
the bootstrap-ordering lesson from ADR-0011 - the destination endpoint has to already exist and be
able to answer the validation handshake before Event Grid will accept the subscription update.

## Consequences

- Confirmed working end-to-end: a real blob write triggered Event Grid, which called the new
  endpoint, which fired successfully (`on_raw_data_created` returned 200, no exceptions) and called
  GitHub's `repository_dispatch` API successfully. The only remaining gap was GitHub Actions' own
  concurrent platform-wide outage delaying the actual `dbt.yml` run - not a bug in anything here.
- The `raw-data-events` Storage Queue is no longer needed and was removed.
- **`raw_writer` (the webhook-ingestion queue trigger on `monzo-webhook`) almost certainly has this
  exact same problem and hasn't been proven working with real traffic yet** - it's the same trigger
  type on the same Flex Consumption app. Not fixed here (out of scope for what was asked), but a
  known, flagged risk: the webhook path may currently be silently unreliable in the same way
  `reconcile` and `on_raw_data_created` were. Worth the same fix (HTTP-triggered, driven by
  something external) if/when verified broken.
- Every non-HTTP trigger type tried on this Flex Consumption app so far (Timer, Queue) has turned
  out to be unreliable from a scaled-to-zero state. HTTP is now the only trigger mechanism trusted
  by default for anything new built on this app - treat that as the working assumption going
  forward, not something to keep re-discovering per trigger.
