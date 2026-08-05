# 0005. OIDC federated auth for GitHub Actions, not stored secrets

Status: Accepted
Date: 2026-08-04

## Context

GitHub Actions workflows (infra deploy, function deploy, dbt pipeline) need to authenticate to
Azure. The common approach is a Service Principal client secret stored as a GitHub secret, but that's
a long-lived credential that can leak and must be manually rotated.

## Decision

Use OIDC federated credentials: a federated identity credential on the Azure AD app registration
trusts GitHub's OIDC token issuer for this specific repo/branch, and workflows use
`azure/login@v2` with no stored secret.

## Consequences

- No long-lived Azure credential exists in GitHub at all — nothing to leak, nothing to rotate.
- Slightly more Terraform setup (the federated credential resource, scoped to repo + branch/environment).
- Consistent with the rest of the security posture already in the spec (Managed Identity, least-
  privilege RBAC) rather than being the one exception that uses static secrets.
