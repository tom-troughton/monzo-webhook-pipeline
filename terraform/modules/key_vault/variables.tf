variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "location" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "secret_officer_object_ids" {
  description = "Principals granted Key Vault Secrets Officer (read/write/delete secrets) - e.g. the Terraform deployer"
  type        = list(string)
}

variable "secret_reader_principal_ids" {
  description = "Principals granted Key Vault Secrets User (read-only) - e.g. Function App managed identities"
  type        = list(string)
  default     = []
}

variable "monzo_client_id" {
  type      = string
  sensitive = true
}

variable "monzo_client_secret" {
  type      = string
  sensitive = true
}

variable "monzo_refresh_token" {
  description = "Seed value only - the reconciliation Function rotates this in Key Vault directly after first use"
  type        = string
  sensitive   = true
}
