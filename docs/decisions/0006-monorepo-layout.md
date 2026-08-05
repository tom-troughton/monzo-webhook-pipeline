# 0006. Monorepo, organized by architectural layer

Status: Accepted
Date: 2026-08-04

## Context

The project spans infra (Terraform), ingestion (Azure Functions), transformation (dbt), and a query
layer (MCP server) — components that could live in separate repos or one.

## Decision

Single repo, top-level folders matching the architecture diagram: `terraform/`, `functions/`,
`dbt/`, `mcp_server/`, `scripts/`, `docs/`. Not split by environment, not split into per-component
repos.

## Consequences

- One person working across all layers doesn't pay cross-repo coordination overhead (versioning,
  cross-repo PRs) that a polyrepo would impose, and there'd be no payoff for it at this scale.
- A reviewer browsing the repo can map top-level folders directly onto the architecture diagram in
  the spec doc.
- Each component (`functions/`, `dbt/`, `mcp_server/`) keeps its own dependency file
  (`requirements.txt` etc.) rather than one shared root dependency file — they have different
  runtime/version constraints (Functions runtime vs dbt-duckdb vs MCP SDK).
