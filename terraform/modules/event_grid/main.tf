# Near-real-time dbt trigger (docs/decisions/0011-event-grid-trigger-for-dbt-pipeline.md,
# docs/decisions/0015-event-grid-webhook-endpoint.md) - additive to the nightly cron/manual
# dbt.yml triggers, not a replacement for them.

resource "azurerm_eventgrid_system_topic" "raw_blob_created" {
  name                = "evgt-${var.project_name}-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  source_resource_id  = var.storage_account_id
  topic_type          = "Microsoft.Storage.StorageAccounts"
}

# Delivers straight to the Function's HTTP endpoint (webhook_endpoint), not azure_function_endpoint
# (confirmed Azure platform bug - see ADR-0011) or a Storage Queue consumed via queue_trigger
# (queue-triggered functions have the same Flex Consumption scale-to-zero wake-up problem the Timer
# trigger had - see ADR-0015; Event Grid delivered every event to the queue successfully, but
# nothing ever consumed them). HTTP triggers have proven reliable on this app every other time -
# webhook_endpoint requires implementing Event Grid's one-time subscription-validation handshake,
# handled in functions/shared/event_grid.py.
resource "azurerm_eventgrid_system_topic_event_subscription" "raw_blob_created" {
  name                = "evgs-${var.project_name}-${var.environment}-raw"
  system_topic        = azurerm_eventgrid_system_topic.raw_blob_created.name
  resource_group_name = var.resource_group_name

  included_event_types = ["Microsoft.Storage.BlobCreated"]

  subject_filter {
    subject_begins_with = "/blobServices/default/containers/raw/"
  }

  webhook_endpoint {
    url                               = "https://${var.function_app_hostname}/api/on_raw_data_created/${var.event_grid_trigger_secret}"
    max_events_per_batch              = 1
    preferred_batch_size_in_kilobytes = 64
  }
}
