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

variable "storage_account_name" {
  description = "Storage account backing the Function App runtime (AzureWebJobsStorage), accessed via managed identity"
  type        = string
}

variable "storage_account_id" {
  description = "Resource ID of the same storage account, for scoping RBAC role assignments"
  type        = string
}

variable "key_vault_uri" {
  description = "Key Vault URI, passed through as an app setting so function code can read Monzo secrets at runtime"
  type        = string
}

variable "github_repo_owner" {
  description = "GitHub org/user owning the repo, passed through as an app setting for the Event Grid handler's repository_dispatch call"
  type        = string
}

variable "github_repo_name" {
  type = string
}
