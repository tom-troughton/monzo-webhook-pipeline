variable "allowed_app_service_plan_skus" {
  description = "App Service Plan SKUs permitted anywhere in the subscription"
  type        = list(string)
  default     = ["Y1", "F1", "FC1"]
}

variable "allowed_storage_account_skus" {
  description = "Storage Account SKUs permitted anywhere in the subscription - excludes Premium tiers"
  type        = list(string)
  default     = ["Standard_LRS", "Standard_GRS", "Standard_ZRS", "Standard_RAGRS"]
}
