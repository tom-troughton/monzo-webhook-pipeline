# 0001. Treat webhooks as notifications, reconciliation as source of truth

Status: Accepted
Date: 2026-08-04

## Context

Monzo webhook delivery is not guaranteed — deliveries can be delayed, dropped, or duplicated, and
the webhook Function itself could fail (cold start timeout, transient error) without Monzo
successfully retrying forever. A pipeline that trusts the webhook as its only ingestion path will
silently lose transactions with no way to detect it.

## Decision

The webhook path is treated as a low-latency notification only. A separate, scheduled
reconciliation job polls the Monzo API directly and is the authoritative check: it writes any
transaction missing from `raw/` regardless of whether the webhook fired. Deduplication between the
two sources happens downstream at the staging layer (dbt), keyed on `transaction_id`, not at
ingestion.

## Consequences

- The pipeline tolerates webhook Function failures, cold starts, and missed deliveries without data
  loss — they just get caught on the next reconciliation run instead of being fatal.
- Adds a second ingestion path (Timer-triggered Function) and OAuth token-refresh complexity that a
  webhook-only design wouldn't need.
- Requires `raw/` to tolerate the same transaction arriving via both paths — blob naming and staging
  dedup logic must account for this (see event/blob naming by `transaction_id`).
