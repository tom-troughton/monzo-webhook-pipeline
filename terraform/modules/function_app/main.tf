resource "azurerm_application_insights" "main" {
  name                = "appi-${var.project_name}-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  application_type    = "web"

  tags = {
    project     = var.project_name
    environment = var.environment
  }
}

# Flex Consumption deploys from a dedicated blob container (separate from raw/staging/marts),
# read via the Function App's managed identity - no storage key involved.
resource "azurerm_storage_container" "deployments" {
  name                  = "app-package"
  storage_account_id    = var.storage_account_id
  container_access_type = "private"
}

# Flex Consumption (docs/decisions/0012-flex-consumption-hosting-plan.md) - tried after the
# classic Y1 Consumption plan's App Service quota came back permanently blocked
# (subscription-wide capacity hold, not a per-region issue). Still uses an App Service Plan, but
# under the FC1 SKU rather than Y1 - a distinct quota dimension from the one that's blocked.
resource "azurerm_service_plan" "main" {
  name                = "asp-${var.project_name}-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  os_type             = "Linux"
  sku_name            = "FC1"
}

resource "azurerm_function_app_flex_consumption" "main" {
  name                = "func-${var.project_name}-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  service_plan_id     = azurerm_service_plan.main.id

  storage_container_type      = "blobContainer"
  storage_container_endpoint  = "https://${var.storage_account_name}.blob.core.windows.net/${azurerm_storage_container.deployments.name}"
  storage_authentication_type = "SystemAssignedIdentity"

  runtime_name    = "python"
  runtime_version = "3.12"

  # Kept low - a personal, low-traffic webhook has no need to scale wide, and this caps any
  # runaway-cost scenario even though Flex Consumption still bills per actual execution/memory-time
  # used, not per potential ceiling.
  maximum_instance_count = 40
  instance_memory_in_mb  = 512

  identity {
    type = "SystemAssigned"
  }

  site_config {}

  app_settings = {
    KEY_VAULT_URI                         = var.key_vault_uri
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.main.connection_string
    # Identity-based AzureWebJobsStorage - no top-level storage_account_name/storage_uses_managed_identity
    # argument exists on this resource type (unlike azurerm_linux_function_app).
    AzureWebJobsStorage__accountName = var.storage_account_name
  }

  tags = {
    project     = var.project_name
    environment = var.environment
  }
}

# Identity-based AzureWebJobsStorage connections require Blob Data Owner, not just Contributor -
# the Functions host needs it for internal lease/lock management, not just our own blob writes.
# Account-scoped, so this also covers the app-package deployment container above.
resource "azurerm_role_assignment" "storage_blob_data_owner" {
  scope                = var.storage_account_id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = azurerm_function_app_flex_consumption.main.identity[0].principal_id
}

resource "azurerm_role_assignment" "storage_queue_data_contributor" {
  scope                = var.storage_account_id
  role_definition_name = "Storage Queue Data Contributor"
  principal_id         = azurerm_function_app_flex_consumption.main.identity[0].principal_id
}
