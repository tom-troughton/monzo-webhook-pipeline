data "azuread_client_config" "current" {}

resource "azuread_application" "github_actions" {
  display_name = "${var.project_name}-github-actions"
}

resource "azuread_service_principal" "github_actions" {
  client_id = azuread_application.github_actions.client_id
}

# Push to the trusted branch - allowed to plan AND apply.
resource "azuread_application_federated_identity_credential" "branch_push" {
  application_id = azuread_application.github_actions.id
  display_name   = "${var.branch}-branch"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:${var.github_org}/${var.github_repo}:ref:refs/heads/${var.branch}"
}

# Pull requests - plan only in practice, since the workflow gates apply on the branch above.
resource "azuread_application_federated_identity_credential" "pull_request" {
  application_id = azuread_application.github_actions.id
  display_name   = "pull-request"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:${var.github_org}/${var.github_repo}:pull_request"
}

# Contributor manages resources; Terraform also creates RBAC role assignments (Key Vault,
# Storage) as part of this config, which Contributor alone cannot do.
resource "azurerm_role_assignment" "contributor" {
  scope                = var.resource_group_id
  role_definition_name = "Contributor"
  principal_id         = azuread_service_principal.github_actions.object_id
}

resource "azurerm_role_assignment" "user_access_administrator" {
  scope                = var.resource_group_id
  role_definition_name = "User Access Administrator"
  principal_id         = azuread_service_principal.github_actions.object_id
}

# cost_guardrails' policy definitions/assignments are subscription-scoped, not resource-group-scoped.
resource "azurerm_role_assignment" "policy_contributor" {
  scope                = "/subscriptions/${var.subscription_id}"
  role_definition_name = "Resource Policy Contributor"
  principal_id         = azuread_service_principal.github_actions.object_id
}
