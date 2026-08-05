data "azurerm_client_config" "current" {}

resource "random_string" "storage_suffix" {
  length  = 6
  special = false
  upper   = false
}

resource "azurerm_resource_group" "main" {
  name     = "rg-${var.project_name}-${var.environment}"
  location = var.location
}

resource "azurerm_storage_account" "main" {
  name                = "st${var.project_name}${random_string.storage_suffix.result}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  account_tier             = "Standard"
  account_replication_type = "LRS"

  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false

  tags = {
    project     = var.project_name
    environment = var.environment
  }
}

resource "azurerm_storage_container" "layers" {
  for_each = toset(["raw", "staging", "marts"])

  name                  = each.value
  storage_account_id    = azurerm_storage_account.main.id
  container_access_type = "private"
}

module "key_vault" {
  source = "./modules/key_vault"

  project_name        = var.project_name
  environment         = var.environment
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  secret_officer_object_ids = [data.azurerm_client_config.current.object_id]

  monzo_client_id     = var.monzo_client_id
  monzo_client_secret = var.monzo_client_secret
  monzo_refresh_token = var.monzo_refresh_token
}
