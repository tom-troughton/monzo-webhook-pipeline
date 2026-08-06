data "azurerm_client_config" "current" {}

resource "random_string" "kv_suffix" {
  length  = 4
  special = false
  upper   = false
}

resource "azurerm_key_vault" "main" {
  name                = "kv-${var.project_name}-${var.environment}-${random_string.kv_suffix.result}"
  resource_group_name = var.resource_group_name
  location            = var.location
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"

  rbac_authorization_enabled = true
  purge_protection_enabled   = var.environment == "prod"
  soft_delete_retention_days = 90

  tags = {
    project     = var.project_name
    environment = var.environment
  }
}

resource "azurerm_role_assignment" "secrets_officer" {
  for_each             = toset(var.secret_officer_object_ids)
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = each.value
}

resource "azurerm_role_assignment" "secrets_reader" {
  for_each             = toset(var.secret_reader_principal_ids)
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = each.value
}

resource "random_password" "webhook_path_secret" {
  length  = 32
  special = false
}

resource "random_password" "reconcile_trigger_secret" {
  length  = 32
  special = false
}

resource "random_password" "event_grid_trigger_secret" {
  length  = 32
  special = false
}

resource "azurerm_key_vault_secret" "monzo_client_id" {
  name         = "monzo-client-id"
  value        = var.monzo_client_id
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_role_assignment.secrets_officer]

  # Seeded once from the local bootstrap; CI's terraform apply passes a placeholder here
  # (never a real secret) since the value is never touched after initial creation.
  lifecycle {
    ignore_changes = [value]
  }
}

resource "azurerm_key_vault_secret" "monzo_client_secret" {
  name         = "monzo-client-secret"
  value        = var.monzo_client_secret
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_role_assignment.secrets_officer]

  lifecycle {
    ignore_changes = [value]
  }
}

resource "azurerm_key_vault_secret" "monzo_refresh_token" {
  name         = "monzo-refresh-token"
  value        = var.monzo_refresh_token
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_role_assignment.secrets_officer]

  lifecycle {
    ignore_changes = [value]
  }
}

resource "azurerm_key_vault_secret" "webhook_path_secret" {
  name         = "webhook-path-secret"
  value        = random_password.webhook_path_secret.result
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_role_assignment.secrets_officer]
}

resource "azurerm_key_vault_secret" "reconcile_trigger_secret" {
  name         = "reconcile-trigger-secret"
  value        = random_password.reconcile_trigger_secret.result
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_role_assignment.secrets_officer]
}

resource "azurerm_key_vault_secret" "event_grid_trigger_secret" {
  name         = "event-grid-trigger-secret"
  value        = random_password.event_grid_trigger_secret.result
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_role_assignment.secrets_officer]
}

resource "azurerm_key_vault_secret" "github_dispatch_token" {
  name         = "github-dispatch-token"
  value        = var.github_dispatch_token
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_role_assignment.secrets_officer]

  # Rotated manually (fine-grained PATs expire) - CI's terraform apply passes a placeholder,
  # never a real value, same pattern as the Monzo secrets above.
  lifecycle {
    ignore_changes = [value]
  }
}
