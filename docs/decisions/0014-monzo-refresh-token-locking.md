# 0014. Lock around Monzo refresh-token exchanges

Status: Accepted
Date: 2026-08-06

## Context

While testing the newly-fixed `reconcile` trigger, its call to Monzo's `/oauth2/token` endpoint was
rejected: `{"code":"unauthorized.bad_refresh_token", "message":"Bad refresh token"}`. Confirmed
independently (same rejection calling from a local machine, same stored secret) - the refresh token
held in Key Vault was genuinely dead, not a transient error.

Checked Monzo's OAuth documentation: refresh tokens are single-use, rotated on every successful
exchange, and **concurrent refresh attempts using the same token are explicitly disallowed** - if a
second caller presents a token that's already been exchanged (even moments earlier, even by a
legitimate caller), the request fails, and per Monzo's own docs **the only recovery path is a full
new interactive consent flow** - there's no graceful retry.

The exact trigger couldn't be pinned down with certainty - the two local scripts run earlier in the
session (`register_webhook.py`, then `list_webhooks.py`) executed sequentially, not concurrently,
so that specific pairing wasn't the cause. The failed `reconcile` invocation's own exception logs
showed a possible Azure SDK-level retry (the same internal auth error twice, ~1 second apart) that
can't be fully ruled out as a contributing factor. Rather than chase a root cause that may not be
fully knowable from the available logs, the more useful response is to make concurrent use
structurally impossible regardless of what causes an overlap.

## Decision

Wrap the token-refresh exchange (`functions/shared/monzo_auth.py`) in an Azure Blob lease, acquired
before reading the current refresh token from Key Vault and released after the exchange completes.
A second caller arriving while a refresh is in progress waits (bounded retry, 30s timeout) instead
of racing with a stale token value.

The lock blob (`locks/monzo-refresh-token.lock`) is Terraform-provisioned, not created lazily by
application code, so a lease is always acquirable without a bootstrap race of its own.

`reconcile.yml`'s `concurrency: { group: reconcile, cancel-in-progress: false }` already stops that
specific workflow from overlapping with itself; this lock generalizes the same protection to any
caller - local scripts included - not just that one workflow.

## Consequences

- Structurally prevents the specific failure mode Monzo's docs warn about, regardless of which
  caller(s) would otherwise have overlapped.
- One more small piece of infrastructure (a container + a placeholder blob), but reuses the existing
  storage account and needs no new secrets or RBAC grants - both the Function App's managed identity
  and the owner's identity already have account-wide Blob Data Owner/Contributor.
- A caller that can't acquire the lock within 30s raises rather than hanging indefinitely - at this
  project's scale (a handful of calls a day, ever), a genuine 30-second contention is itself a sign
  something else is wrong, not a case worth building deeper retry logic for.
- Doesn't prevent the *first* occurrence of this problem from needing a manual fix - recovering a
  dead refresh token still requires re-running `scripts/monzo_oauth.py`'s interactive consent flow,
  same as always. This is purely a going-forward safeguard.
