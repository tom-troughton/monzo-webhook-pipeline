# 0010. Detecting a dead reconciliation job

Status: Rejected (Azure Monitor approach) - see Consequences for the path forward
Date: 2026-08-05

## Context

[ADR-0001](0001-reconciliation-as-source-of-truth.md) makes the reconciliation Function the
authoritative catch-all for anything the webhook path misses. But nothing currently detects if
reconciliation itself stops working - most plausibly a revoked/expired Monzo refresh token, but
also a Function App outage of any other kind. Without a check, that failure is silent: transactions
would quietly stop being caught until someone happened to notice missing data.

Two designs were considered: an Azure Monitor alert reading the reconciliation Function's own
Application Insights telemetry, versus an independent scheduled GitHub Actions workflow. The
Azure Monitor version was built as a heartbeat-style scheduled query rule (fires when there's been
no *successful* `reconcile` execution in the trailing 24h, rather than reacting to a specific logged
exception, so it also catches the Function never running at all) - see the reverted
`terraform/modules/monitoring/` for the design.

## Decision

Rejected on cost: log-based Azure Monitor scheduled query rules aren't part of Azure's always-free
tier (unlike simple metric alerts, which get 10 free/month) - roughly $1-3/month depending on
evaluation frequency, even at the cheapest 6-hourly evaluation cadence. Given this project's zero-
tolerance cost-discipline stance (see CLAUDE.md), a recurring paid cost for an alert that may never
fire wasn't judged worth it.

## Consequences

- No Azure Monitor alert exists yet for this failure mode - it remains a real, currently-unaddressed
  gap.
- The path forward, if revisited: reuse the same heartbeat *logic* (no successful `reconcile` run in
  24h) but execute it from a scheduled GitHub Actions workflow querying Application Insights/Log
  Analytics read-only via the Azure Monitor API, rather than a native Azure Monitor alert resource.
  This keeps the detection free (GitHub Actions minutes are free on a public repo; Log Analytics
  queries at this volume don't carry a separate charge) and needs only a read-only "Monitoring
  Reader"-type RBAC grant for the CI identity - no Key Vault access, unlike the earlier GitHub-Actions
  design considered in the original discussion (an active Monzo token-refresh check), which was
  already ruled out for needing Key Vault read+write and risking a token-rotation race with the
  reconciliation Function.
- Not yet built. Revisit once there's appetite to spend the implementation effort on the free-tier
  version, or if the cost tolerance changes.
