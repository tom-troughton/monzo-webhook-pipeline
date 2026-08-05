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

resource "azurerm_service_plan" "main" {
  name                = "asp-${var.project_name}-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  os_type             = "Linux"
  sku_name            = "Y1"
}

resource "azurerm_linux_function_app" "main" {
  name                = "func-${var.project_name}-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  service_plan_id     = azurerm_service_plan.main.id

  storage_account_name          = var.storage_account_name
  storage_uses_managed_identity = true

  identity {
    type = "SystemAssigned"
  }

  site_config {
    application_stack {
      python_version = "3.12"
    }
  }

  app_settings = {
    KEY_VAULT_URI                         = var.key_vault_uri
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.main.connection_string
  }

  tags = {
    project     = var.project_name
    environment = var.environment
  }
}

# Identity-based AzureWebJobsStorage connections require Blob Data Owner, not just Contributor -
# the Functions host needs it for internal lease/lock management, not just our own blob writes.
resource "azurerm_role_assignment" "storage_blob_data_owner" {
  scope                = var.storage_account_id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = azurerm_linux_function_app.main.identity[0].principal_id
}

resource "azurerm_role_assignment" "storage_queue_data_contributor" {
  scope                = var.storage_account_id
  role_definition_name = "Storage Queue Data Contributor"
  principal_id         = azurerm_linux_function_app.main.identity[0].principal_id
}
