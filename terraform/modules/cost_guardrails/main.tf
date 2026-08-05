data "azurerm_subscription" "current" {}

# This project is fully serverless/PaaS - a VM is never intentional and is the single
# largest accidental-cost risk (see CLAUDE.md "Cost discipline").
resource "azurerm_policy_definition" "deny_vm_creation" {
  name         = "deny-virtual-machines"
  policy_type  = "Custom"
  mode         = "All"
  display_name = "Deny virtual machine creation"
  description  = "This project has no use for VMs; block them to prevent accidental standing cost."

  policy_rule = jsonencode({
    if = {
      field = "type"
      in = [
        "Microsoft.Compute/virtualMachines",
        "Microsoft.Compute/virtualMachineScaleSets",
      ]
    }
    then = {
      effect = "deny"
    }
  })
}

resource "azurerm_subscription_policy_assignment" "deny_vm_creation" {
  name                 = "deny-virtual-machines"
  policy_definition_id = azurerm_policy_definition.deny_vm_creation.id
  subscription_id      = data.azurerm_subscription.current.id
  display_name         = "Deny virtual machine creation"
}

resource "azurerm_policy_definition" "restrict_app_service_sku" {
  name         = "restrict-app-service-plan-sku"
  policy_type  = "Custom"
  mode         = "All"
  display_name = "Restrict App Service Plan SKU to Consumption/Free tiers"
  description  = "Only Consumption (Y1), Flex Consumption (FC1), or Free (F1) App Service Plan SKUs are allowed, per ADR-0003/0012."

  policy_rule = jsonencode({
    if = {
      allOf = [
        {
          field  = "type"
          equals = "Microsoft.Web/serverfarms"
        },
        {
          field = "Microsoft.Web/serverfarms/sku.name"
          notIn = var.allowed_app_service_plan_skus
        },
      ]
    }
    then = {
      effect = "deny"
    }
  })
}

resource "azurerm_subscription_policy_assignment" "restrict_app_service_sku" {
  name                 = "restrict-app-service-plan-sku"
  policy_definition_id = azurerm_policy_definition.restrict_app_service_sku.id
  subscription_id      = data.azurerm_subscription.current.id
  display_name         = "Restrict App Service Plan SKU"
}

resource "azurerm_policy_definition" "restrict_storage_sku" {
  name         = "restrict-storage-account-sku"
  policy_type  = "Custom"
  mode         = "All"
  display_name = "Restrict Storage Account SKU to Standard tiers"
  description  = "Denies Premium storage account SKUs - this project only needs Standard blob storage."

  policy_rule = jsonencode({
    if = {
      allOf = [
        {
          field  = "type"
          equals = "Microsoft.Storage/storageAccounts"
        },
        {
          field = "Microsoft.Storage/storageAccounts/sku.name"
          notIn = var.allowed_storage_account_skus
        },
      ]
    }
    then = {
      effect = "deny"
    }
  })
}

resource "azurerm_subscription_policy_assignment" "restrict_storage_sku" {
  name                 = "restrict-storage-account-sku"
  policy_definition_id = azurerm_policy_definition.restrict_storage_sku.id
  subscription_id      = data.azurerm_subscription.current.id
  display_name         = "Restrict Storage Account SKU"
}
