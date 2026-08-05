# 0003. Consumption plan (not Premium) for the webhook Function App

Status: Accepted
Date: 2026-08-05

## Context

The webhook Function benefits from fast, warm responses to avoid Monzo webhook timeouts/retries. A
Premium (pre-warmed, always-on) Functions plan would minimize cold starts, but this project runs on
an Azure free-tier budget with no standing monthly cost tolerated. Premium realistically costs
$150+/month — incompatible with that constraint.

## Decision

Use the Consumption plan for all Functions, including the webhook. Accept occasional cold starts
rather than pay for Premium.

## Consequences

- Zero/near-zero hosting cost, consistent with the free-tier constraint (Consumption has an
  always-free monthly grant of 1M executions + 400,000 GB-s, far above personal transaction volume).
- Occasional cold-start delay on the webhook path is accepted as a tolerable tradeoff rather than
  engineered away, because [0001](0001-reconciliation-as-source-of-truth.md) already means a slow or
  missed webhook response isn't a data-loss risk — reconciliation catches it. The cost constraint
  didn't force a design compromise; it just meant leaning on a reliability pattern already in place.
