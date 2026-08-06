# 0013. Drive reconciliation from GitHub Actions, not a native Timer trigger

Status: Accepted
Date: 2026-08-06

## Context

`reconcile` was originally a Timer-triggered Function (`schedule="0 0 */6 * * *"`, `run_on_startup=False`)
— the natural choice, and the pattern the spec assumes. After the Function App was deployed and live
for several hours spanning two scheduled ticks (00:00 and 06:00 UTC), it had **zero invocations
ever**, confirmed by querying Application Insights (`AppRequests`, workspace-based schema) directly.

Tracing host restart events (`AppTraces` "Found the following functions" entries) showed the
Function App was completely idle - no running host instance at all - from 23:48 UTC to 07:17 UTC,
over 7 hours spanning both missed ticks. It only came back to life because of an unrelated manual
`curl` against the HTTP-triggered `webhook` route, which forced a cold start. A Timer trigger has no
external caller to force that same wake-up.

This is a known, documented Flex Consumption limitation, not specific to this app: when the app
scales to zero, there's no running host to hold the timer's schedule lease, so the tick is silently
missed rather than queued or caught up later. See:
- [Why would a Timer Triggered Function in Flex Consumption stop invoking... only resume after a manual restart?](https://learn.microsoft.com/en-us/answers/questions/5779826/why-would-a-timer-triggered-azure-function-in-flex)
- [Flex Consumption timer functions are killed (azure-functions-host#10527)](https://github.com/Azure/azure-functions-host/issues/10527)
- [Timer trigger on Flex Consumption gets terminated early](https://learn.microsoft.com/en-sg/answers/questions/5900705/timer-trigger-on-flex-consumption-gets-terminated)

This matters more than an ordinary rough edge: `reconcile` isn't incidental, it's the reliability
backbone [ADR-0001](0001-reconciliation-as-source-of-truth.md) depends on - webhooks are explicitly
*not* the source of truth precisely because reconciliation is supposed to catch what they miss. A
reconciliation job that can silently stop firing undermines that guarantee entirely, silently.

## Decision

Replace the Timer trigger with an HTTP-triggered route (`reconcile/{path_secret}`), guarded by a
path secret in Key Vault (`reconcile-trigger-secret`, generated the same way as
`webhook-path-secret` - see the new shared `functions/shared/path_secret.py`, factored out of
`payload_validation.py` since there are now two routes needing the same check). A new scheduled
GitHub Actions workflow (`.github/workflows/reconcile.yml`) calls it on the same 6-hourly cadence
(`workflow_dispatch` also available for manual runs).

This mirrors the fix already applied to the Event Grid trigger in
[ADR-0011](0011-event-grid-trigger-for-dbt-pipeline.md): when a Flex Consumption native trigger
mechanism proves unreliable, drive the Function from something external instead of trying to work
around the platform's internal behavior.

The Timer trigger wasn't kept as a fallback alongside the HTTP route - it demonstrably doesn't work,
so keeping it would only be false reassurance, not real redundancy.

## Consequences

- Reconciliation's reliability now depends on GitHub Actions' scheduler instead of Azure's - not
  perfectly precise (GitHub documents that scheduled workflows can be delayed under load), but
  actually fires, which the previous mechanism didn't.
- Same secretless-except-here exception pattern as the webhook route: an unguessable path secret is
  the only auth, since there's no signing scheme to verify against (this time it's not Monzo calling
  us, it's our own GitHub Actions runner - a shared secret is still the simplest correct mechanism).
- One more Key Vault secret to account for if this is ever audited or rotated.
- Worth revisiting if the underlying Flex Consumption timer-trigger bug gets fixed, but no urgency -
  the GitHub Actions path works and isn't meaningfully worse than a native timer would have been.
- This wasn't caught before deployment because nothing was watching for a Timer trigger *not*
  firing - exactly the class of gap the (cost-rejected) heartbeat alert in
  [ADR-0010](0010-reconciliation-heartbeat-alert.md) was designed to catch. Worth reconsidering
  now that the underlying risk has materialized once already, not just been theoretical.
