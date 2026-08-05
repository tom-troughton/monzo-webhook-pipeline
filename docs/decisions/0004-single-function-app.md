# 0004. Single Function App with multiple triggers

Status: Accepted
Date: 2026-08-04

## Context

Ingestion needs three separate triggers: HTTP (webhook), Queue (raw blob writer), and Timer
(reconciliation). These could be three separate Function Apps or one app hosting three functions.

## Decision

One Function App, three functions, using the Python v2 programming model (decorator-based, single
`function_app.py` entry point). Shared logic (Monzo client, OAuth token refresh, blob writer,
payload validation) lives once in `functions/shared/`.

## Consequences

- Avoids duplicating the Monzo client/token-refresh code across multiple deployable units.
- One deployment, one `requirements.txt`, one set of app settings/Managed Identity to manage in
  Terraform — less infra surface than three separate apps.
- Couples the three functions' deployment lifecycle together — a change to the reconciliation logic
  redeploys the webhook function too. Acceptable at this scale; would reconsider if the functions
  needed independent scaling or release cadences.
