output "client_id" {
  value = azuread_application.github_actions.client_id
}

output "tenant_id" {
  value = data.azuread_client_config.current.tenant_id
}

output "principal_id" {
  value = azuread_service_principal.github_actions.object_id
}
