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

variable "storage_account_id" {
  type = string
}

variable "function_app_hostname" {
  description = "Default hostname of the Function App hosting the on_raw_data_created HTTP route"
  type        = string
}

variable "event_grid_trigger_secret" {
  description = "Path secret embedded in the webhook_endpoint URL - the only auth Event Grid's webhook destination type supports"
  type        = string
  sensitive   = true
}
