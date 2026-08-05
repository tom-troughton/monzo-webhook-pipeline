# 0012. Switch the Function App hosting plan from Y1 Consumption to Flex Consumption (FC1)

Status: Accepted
Date: 2026-08-06

## Context

The classic `Y1` Consumption plan ([ADR-0003](0003-consumption-plan-for-webhook.md)) has been
permanently blocked since deployment was first attempted: Azure's App Service quota for `Y1`/Total
Regional VMs sits at 0 across every region tried, confirmed subscription-wide via direct ARM API
checks. A formal quota-increase request came back from Azure's Capacity Management team as an
explicit "unable to approve at this time... additional capacity" response - a genuine capacity
constraint, not a policy/eligibility gate, with no committed timeline for resolution.

Flex Consumption is a newer Functions hosting model, GA in the region list that includes UK South.
Critically, it's a *different* App Service Plan SKU (`FC1`) from `Y1` - a distinct quota dimension
in Azure's backend, plausibly unaffected by the capacity hold on `Y1` specifically. It's still fully
consumption-priced (no Premium/dedicated tier involved), so it doesn't conflict with the cost-
discipline constraint that ruled out Premium in ADR-0003.

## Decision

Switch `terraform/modules/function_app/` from `azurerm_service_plan` (`Y1`) +
`azurerm_linux_function_app` to `azurerm_service_plan` (`FC1`) + `azurerm_function_app_flex_consumption`.
No changes to `functions/function_app.py` - HTTP, Queue, and Timer triggers work identically under
Flex Consumption.

Confirmed empirically: `terraform apply` succeeded and the Function App is now `Running`
(`func-monzode-dev.azurewebsites.net`) - the FC1 quota was not subject to the same capacity hold as
Y1.

One unrelated blocker surfaced and was fixed along the way: the `cost_guardrails` module's
[Azure Policy allowlist](0003-consumption-plan-for-webhook.md) (`allowed_app_service_plan_skus`)
predated Flex Consumption and only listed `["Y1", "F1"]`, so the project's own guardrail rejected
the `FC1` service plan on the first apply attempt with a `RequestDisallowedByPolicy` error - not a
quota issue. Added `"FC1"` to the allowlist, consistent with the policy's stated intent
("Consumption/Free tiers only").

## Consequences

- The Function App exists for the first time since the project's inception - infrastructure is no
  longer blocked. Deploying the actual function code (`func azure functionapp publish`, via
  `deploy.yml`'s `deploy-functions` job) is the remaining step to make the webhook/queue/
  reconciliation path live.
- Flex Consumption requires a dedicated deployment blob container (`app-package`, in the same
  storage account), read via the Function App's managed identity - a new resource, but no new RBAC
  grant, since the identity already has account-wide `Storage Blob Data Owner`.
- `AzureWebJobsStorage` is now wired via the `AzureWebJobsStorage__accountName` app setting
  (identity-based connection) rather than the `storage_account_name`/`storage_uses_managed_identity`
  top-level arguments used on `azurerm_linux_function_app` - those arguments don't exist on
  `azurerm_function_app_flex_consumption`.
- Explicit scaling limits are now required rather than fully implicit (`maximum_instance_count = 40`,
  `instance_memory_in_mb = 512`) - set low, since a personal low-traffic webhook has no need to scale
  wide; this caps a runaway-cost scenario even though billing is still per actual execution/
  memory-time used, not per potential ceiling.
- Still no explanation for *why* Y1 specifically is capacity-constrained subscription-wide, or
  whether it will ever clear - that support ticket remains open regardless, tracked separately.
