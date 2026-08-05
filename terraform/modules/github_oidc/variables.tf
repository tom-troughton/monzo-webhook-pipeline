variable "project_name" {
  type = string
}

variable "github_org" {
  type = string
}

variable "github_repo" {
  type = string
}

variable "branch" {
  description = "Branch trusted to run terraform apply (not just plan)"
  type        = string
  default     = "master"
}

variable "resource_group_id" {
  description = "Resource group GitHub Actions manages day to day"
  type        = string
}

variable "subscription_id" {
  description = "Subscription ID, for the subscription-scoped Resource Policy Contributor grant the cost_guardrails module needs"
  type        = string
}
