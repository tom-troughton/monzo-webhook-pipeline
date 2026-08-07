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
    # Read directly by our own code (shared/blob_writer.py, shared/monzo_auth.py's lock) - a
    # distinct setting from AzureWebJobsStorage__accountName above, which the Functions host uses
    # for its own internal bindings. Missing this was a silent bug: it only "worked" locally
    # because .env sets it there, and .env never deploys - nothing caught it until reconcile
    # actually ran far enough in the deployed app to hit code that needed it.
    STORAGE_ACCOUNT_NAME = var.storage_account_name
    # Read by shared/github_dispatch.py's Event Grid handler (docs/decisions/0011).
    GITHUB_REPO_OWNER = var.github_repo_owner
    GITHUB_REPO_NAME  = var.github_repo_name
    # The host's default (Blob, in azure-webjobs-secrets) fails to authenticate under an
    # identity-only AzureWebJobsStorage connection - that internal operation apparently still
    # needs account-key auth, which we don't provide. Irrelevant anyway since every route here
    # uses AuthLevel.ANONYMOUS and never touches function-level keys - just stop the host
    # managing them via blob storage at all. See docs/decisions/0013.
    AzureWebJobsSecretStorageType = "files"
  }

  tags = {
    project     = var.project_name
    environment = var.environment
  }

  # Azure reflects APPLICATIONINSIGHTS_CONNECTION_STRING (set via app_settings above) back onto
  # this site_config attribute after every deploy; config here has no opinion on it, so Terraform
  # would otherwise "fix" it to null on every single apply - a real Function App update/restart
  # each time, for a value that's already correctly set via app_settings regardless.
  #
  # The app_settings entry is the mirror image of the same round-trip, and needs ignoring for the
  # same reason. Once Azure surfaces the value on site_config, the provider stops reporting it in
  # app_settings, so Terraform sees it as missing and plans to add it back - forever. It is a diff
  # that applying cannot resolve: `terraform apply` succeeded, and the very next `terraform plan`
  # proposed the identical change again. Confirmed not to be a real absence - `az functionapp
  # config appsettings list` shows the setting present on the running app - so ignoring this keeps
  # App Insights working while making plans honest. Without it every apply updates the Function
  # App for nothing, which is exactly the churn the site_config ignore above was added to stop.
  lifecycle {
    ignore_changes = [
      site_config[0].application_insights_connection_string,
      app_settings["APPLICATIONINSIGHTS_CONNECTION_STRING"],
    ]
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

