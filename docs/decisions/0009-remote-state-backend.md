# 0009. Remote Terraform state, in a storage account Terraform doesn't manage

Status: Accepted
Date: 2026-08-05

## Context

Terraform was using local state (`terraform.tfstate` on the developer's machine, gitignored).
Once GitHub Actions needs to run `terraform plan`/`apply` from a fresh checkout ([ADR-0005](0005-oidc-for-github-actions.md)),
CI and the local developer must read/write the same state, or CI's fresh-checkout run sees no
existing resources and tries to recreate everything from scratch.

The state backend also can't be a resource inside the same Terraform config that uses it: if the
storage account holding the state were itself managed by that config, a `terraform destroy` (or
even certain applies) could delete or lock the blob holding the state while Terraform is mid-read of
that very blob - a config must never be able to destroy its own backend out from under itself.

## Decision

State lives in Azure Blob Storage, in a storage account + resource group (`rg-monzode-tfstate`)
created once via `az` CLI, deliberately outside this Terraform config's management. Authentication
uses Azure AD RBAC (`use_azuread_auth = true`, `Storage Blob Data Contributor`), not a storage
account key, consistent with avoiding connection strings/keys elsewhere in the project. The RBAC
role assignments granting access to that storage account (for the developer and for the GitHub
Actions service principal from [ADR-0005](0005-oidc-for-github-actions.md)) *are* managed by the
main config - granting/revoking access doesn't risk deleting the backend itself, so it's safe to
keep in Terraform rather than as more untracked manual steps.

## Consequences

- CI and local `terraform` commands now operate on the same state - no more risk of CI recreating
  already-existing resources.
- The `rg-monzode-tfstate` resource group, its storage account, and the `tfstate` container are the
  one deliberate exception to "everything is Terraform-managed" in this project - they exist only as
  a handful of one-off `az` CLI commands, documented here rather than in code.
- If this state storage account is ever lost, there's no Terraform config to recreate it from -
  it would need to be rebuilt manually and state re-migrated (or resources re-imported).
