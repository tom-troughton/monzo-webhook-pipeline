output "resource_group_name" {
  value = azurerm_resource_group.main.name
}

output "storage_account_name" {
  value = azurerm_storage_account.main.name
}

output "storage_account_primary_blob_endpoint" {
  value = azurerm_storage_account.main.primary_blob_endpoint
}

output "key_vault_name" {
  value = module.key_vault.key_vault_name
}

output "key_vault_uri" {
  value = module.key_vault.key_vault_uri
}

output "function_app_name" {
  value = module.function_app.function_app_name
}

output "function_app_default_hostname" {
  value = module.function_app.default_hostname
}

output "github_actions_client_id" {
  description = "Set as the AZURE_CLIENT_ID repo variable (not secret - OIDC needs no client secret)"
  value       = module.github_oidc.client_id
}

output "github_actions_tenant_id" {
  description = "Set as the AZURE_TENANT_ID repo variable"
  value       = module.github_oidc.tenant_id
}

output "subscription_id" {
  description = "Set as the AZURE_SUBSCRIPTION_ID repo variable"
  value       = data.azurerm_client_config.current.subscription_id
}
