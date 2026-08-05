output "policy_assignment_ids" {
  value = [
    azurerm_subscription_policy_assignment.deny_vm_creation.id,
    azurerm_subscription_policy_assignment.restrict_app_service_sku.id,
    azurerm_subscription_policy_assignment.restrict_storage_sku.id,
  ]
}
