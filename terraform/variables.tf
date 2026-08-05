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

variable "github_org" {
  description = "GitHub org/user that owns the repo, for scoping the OIDC federated credential"
  type        = string
  default     = "tom-troughton"
}

variable "github_repo" {
  type    = string
  default = "monzo-webhook-pipeline"
}
