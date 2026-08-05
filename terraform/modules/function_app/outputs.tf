output "function_app_name" {
  value = azurerm_function_app_flex_consumption.main.name
}

output "principal_id" {
  value = azurerm_function_app_flex_consumption.main.identity[0].principal_id
}

output "default_hostname" {
  value = azurerm_function_app_flex_consumption.main.default_hostname
}

output "application_insights_id" {
  value = azurerm_application_insights.main.id
}
