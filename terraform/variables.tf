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
