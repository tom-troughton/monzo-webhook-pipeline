data "azurerm_client_config" "current" {}

module "cost_guardrails" {
  source = "./modules/cost_guardrails"
}

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

resource "azurerm_storage_queue" "webhook" {
  name               = "monzo-webhook"
  storage_account_id = azurerm_storage_account.main.id
}

module "key_vault" {
  source = "./modules/key_vault"

  project_name        = var.project_name
  environment         = var.environment
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  secret_officer_object_ids = [
    var.owner_object_id,
    module.github_oidc.principal_id,
  ]

  monzo_client_id     = var.monzo_client_id
  monzo_client_secret = var.monzo_client_secret
  monzo_refresh_token = var.monzo_refresh_token
}

module "function_app" {
  source = "./modules/function_app"

  project_name        = var.project_name
  environment         = var.environment
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  storage_account_name = azurerm_storage_account.main.name
  storage_account_id   = azurerm_storage_account.main.id
  key_vault_uri        = module.key_vault.key_vault_uri
}

resource "azurerm_role_assignment" "function_app_kv_reader" {
  scope                = module.key_vault.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = module.function_app.principal_id
}

module "github_oidc" {
  source = "./modules/github_oidc"

  project_name   = var.project_name
  github_org     = var.github_org
  github_repo    = var.github_repo
  github_org_id  = var.github_org_id
  github_repo_id = var.github_repo_id

  resource_group_id = azurerm_resource_group.main.id
  subscription_id   = data.azurerm_client_config.current.subscription_id
}

# Remote state backend - resource group, storage account and container are deliberately NOT
# managed here (see docs/decisions/0009-remote-state-backend.md): a config must never be able to
# destroy the very backend holding its own state mid-operation. RBAC grants onto it are safe to
# manage here since they don't risk deleting the backend itself.
data "azurerm_storage_account" "tfstate" {
  name                = "stmonzodetfstate130dc0"
  resource_group_name = "rg-monzode-tfstate"
}

resource "azurerm_role_assignment" "tfstate_owner" {
  scope                = data.azurerm_storage_account.tfstate.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = var.owner_object_id
}

resource "azurerm_role_assignment" "tfstate_github_actions" {
  scope                = data.azurerm_storage_account.tfstate.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = module.github_oidc.principal_id
}
