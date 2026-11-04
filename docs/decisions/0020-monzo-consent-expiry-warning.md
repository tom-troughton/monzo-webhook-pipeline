# 0020. Warn ahead of Monzo's 90-day consent expiry

Status: Accepted
Date: 2026-11-04

## Context

Monzo requires the account holder to interactively re-approve API access every 90 days.
Refreshing the access token does not reset this - only `scripts/monzo_oauth.py`'s
authorization-code flow plus the in-app approval does. The pipeline first hit it on 2026-11-03,
90 days after the 2026-08-05 re-authorisation done for the full-history backfill: the refresh
grant kept succeeding (Key Vault showed the token rotating normally), but `GET /accounts`
returned 403, so `reconcile` failed with a generic 500 every run.

Two things made this worse than it needed to be:

1. **It was detected only after it broke.** ADR-0017's heartbeat catches a dead ingestion path,
   but only after 24h of missed runs. Yet this failure is entirely predictable - it happens on a
   fixed date known from the moment consent is granted.
2. **The failure was opaque.** The reconcile workflow discarded the response body and reported
   only "HTTP 500"; the cause (`403 Forbidden for url: https://api.monzo.com/accounts`) was only
   visible by querying Application Insights for the correlated exception.

## Decision

- **Record the consent time.** `scripts/monzo_oauth.py` writes `ops/monzo-consent.json`
  (`{"consented_at": ...}`, via `functions/shared/consent.py`) after the user confirms the in-app
  approval - the approval, not the code exchange, is what starts the clock. It lives in `ops/`
  next to the heartbeat for the same reason (outside Event Grid's `raw/` subject filter). The
  marker was seeded once by hand at 2026-11-04T10:40:09Z, the timestamp of that morning's
  re-authorisation (the authorization-code exchange's Key Vault secret version).
- **Warn from day 80.** `pipeline_health.yml` fails once the marker is 80+ days old, giving about
  10 days' notice. It repeats daily until renewed - one email per run, which is the point. A
  missing marker also fails, since expiry then can't be predicted.
- **Name the failure when it happens anyway.** `fetch_accounts()` raises `MonzoConsentRequired` on
  a 403, and `reconcile` returns a 503 carrying that message instead of an unhandled 500.
  `reconcile.yml` now prints the response body, so the workflow run says what to do. Only
  `/accounts` is mapped this way: a 403 from `/transactions` is usually
  `forbidden.verification_required` for a window older than recent consent permits (the backfill
  script hits it routinely), which is a different problem.

## Consequences

- One extra blob read per daily health check; no new resources and no cost.
- The marker is only as accurate as its writes. Revoking access in the Monzo app, or Monzo
  changing the 90-day period, would break things before the warning fires - the heartbeat check
  remains the backstop for those, and the 503 message now names the cause either way.
- A 403 on `/accounts` for some other reason (e.g. an app permission change) will be reported as
  "consent lapsed". Accepted: re-running the OAuth flow is the fix for every 403 case on that
  endpoint anyway, and the Monzo error code is included in the message.
