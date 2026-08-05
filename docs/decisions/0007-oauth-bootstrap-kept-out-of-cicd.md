# 0007. Monzo OAuth bootstrap is a manual local script, never run in CI

Status: Accepted
Date: 2026-08-04

## Context

Getting the first Monzo refresh token requires an interactive OAuth consent flow — a human
approving access in a browser and a redirect/auth code exchange. This is fundamentally different
from the ongoing token-refresh logic (using an existing refresh token to get a new access token),
which is unattended runtime code.

## Decision

The one-time/occasional interactive grant lives in `scripts/monzo_oauth.py`, run manually and
locally using the developer's own `az login` session to write the resulting refresh token to Key
Vault. It is never invoked by any GitHub Actions workflow. The reusable OAuth exchange logic it
depends on should live in `functions/shared/` so both the bootstrap script and the runtime
token-refresh code call the same implementation rather than duplicating it.

## Consequences

- Keeps the one script that handles raw OAuth secrets and requires human consent out of any
  automated pipeline — nothing in CI can trigger or replay this flow.
- Requires the developer to run it manually if the refresh token is ever revoked/invalidated;
  this is an accepted operational step, not something to automate away.
- `scripts/` is established as the location for manual/local-only operational tooling generally
  (also `kv.py`, `monzo_check.py`), distinct from `functions/` (deployed) — see
  [0006](0006-monorepo-layout.md).
