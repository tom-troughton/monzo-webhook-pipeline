# 0016. Webhook writes directly to raw/, no Storage Queue buffer

Status: Accepted
Date: 2026-08-06

## Context

[ADR-0002](0002-storage-queue-buffer.md) put a Storage Queue between the webhook's HTTP handler and
the blob write specifically so a slow/failed write couldn't delay or fail the response to Monzo, and
to get automatic retry via the queue trigger's built-in redelivery/poison-queue handling.

Two things fixed since then invalidate that reasoning:

- [ADR-0015](0015-event-grid-webhook-endpoint.md) confirmed - by direct testing, not just reading
  docs - that queue-triggered functions on this Flex Consumption app have the same scale-to-zero
  wake-up problem Timer triggers had ([ADR-0013](0013-externally-triggered-reconciliation.md)).
  `raw_writer` (the queue trigger this ADR removes) was never proven to actually consume a message
  with real traffic - it's the same trigger type that just turned out to be unreliable elsewhere on
  this app.
- That makes the queue actively worse than no queue at all: a failed or stuck write becomes a
  silent, unbounded hang (nothing ever retries it, nothing ever surfaces the failure) instead of a
  visible one Monzo's own webhook retry behavior would catch.

Unlike the Event Grid case, there's no external service on the other end of this queue to
reconfigure around - `webhook` and `raw_writer` are both our own code. Keeping the queue and driving
`raw_writer` externally (GitHub Actions, the pattern used for `reconcile`) would just reintroduce
polling latency for no reason, since we control both sides and can simply not have an intermediate
hop at all.

## Decision

Merge `webhook` and `raw_writer` into a single HTTP-triggered function that calls
`write_transaction()` directly. Removed: the `monzo-webhook` Storage Queue, the `raw_writer`
function, and the `Storage Queue Data Contributor` role grant (no queues remain in the project after
this, so the grant was no longer needed by anything).

## Consequences

- A failed or slow blob write is now a failed or slow *webhook response* to Monzo, not a silently
  dropped queue message. Monzo retries failed webhook deliveries on its own - a real, working retry
  mechanism, unlike the queue trigger it replaces. `write_transaction()` is already idempotent
  (deterministic naming by `transaction_id`), so a retried delivery is harmless.
- Reconciliation ([ADR-0001](0001-reconciliation-as-source-of-truth.md)) remains the ultimate
  safety net regardless - this doesn't weaken that guarantee, it just makes the fast path actually
  trustworthy instead of silently unverified.
- Net simplification, not added complexity: one fewer Function, one fewer Azure resource, one fewer
  RBAC grant. Unlike the Event Grid fix, this didn't need new code to work around a platform
  limitation - just removing a layer that no longer earned its keep.
- Blob writes are fast (sub-second) at this project's scale, so webhook response latency shouldn't
  meaningfully change. Cold-start latency on a scaled-to-zero HTTP trigger is the same accepted
  trade-off as [ADR-0003](0003-consumption-plan-for-webhook.md) already made.
