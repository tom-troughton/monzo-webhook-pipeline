variable "project_name" {
  description = "Short name used to prefix resource names"
  type        = string
  default     = "monzode"
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "uksouth"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "dev"
}

variable "monzo_client_id" {
  description = "Monzo OAuth client ID"
  type        = string
  sensitive   = true
}

variable "monzo_client_secret" {
  description = "Monzo OAuth client secret"
  type        = string
  sensitive   = true
}

variable "monzo_refresh_token" {
  description = "Monzo OAuth refresh token (seed value only - the reconciliation Function rotates this in Key Vault directly after first use)"
  type        = string
  sensitive   = true
}

variable "owner_object_id" {
  description = "The human deployer's AAD object ID. NOT data.azurerm_client_config.current.object_id - that resolves to whoever is CURRENTLY authenticated (the GitHub Actions service principal in CI, not necessarily this person), which caused CI to see this person fall out of a for_each set and destroy their own Key Vault access."
  type        = string
  default     = "3e0da827-6351-4cf8-8fe3-8c84f46f4930"
}

variable "github_org" {
  description = "GitHub org/user that owns the repo, for scoping the OIDC federated credential"
  type        = string
  default     = "tom-troughton"
}

variable "github_repo" {
  type    = string
  default = "monzo-webhook-pipeline"
}

variable "github_org_id" {
  description = "Numeric GitHub owner ID - visible in the failed workflow's OIDC subject claim, or via `gh api users/<org>`"
  type        = string
  default     = "88544233"
}

variable "github_repo_id" {
  description = "Numeric GitHub repository ID - see github_org_id"
  type        = string
  default     = "1323382936"
}
