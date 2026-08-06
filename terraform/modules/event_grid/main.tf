# Near-real-time dbt trigger (docs/decisions/0011-event-grid-trigger-for-dbt-pipeline.md) -
# additive to the nightly cron/manual dbt.yml triggers, not a replacement for them.

resource "azurerm_eventgrid_system_topic" "raw_blob_created" {
  name                = "evgt-${var.project_name}-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  source_resource_id  = var.storage_account_id
  topic_type          = "Microsoft.Storage.StorageAccounts"
}

# Delivers to a Storage Queue, not directly to the Function via azure_function_endpoint - that
# destination type hits a confirmed Azure platform bug (reproduces identically via the Portal and
# Terraform: "Endpoint validation: Destination endpoint not found... Resource should pre-exist",
# even when the function demonstrably already exists and is correctly indexed). Storage Queue
# destinations skip whatever extra function-indexing layer that validation depends on - the queue
# itself is visible to Event Grid the instant Terraform creates it, no separate discovery step.
resource "azurerm_storage_queue" "raw_data_events" {
  name               = "raw-data-events"
  storage_account_id = var.storage_account_id
}

# Subject-filtered to raw/ specifically, not the whole storage account - staging/ and marts/ live
# on the same account and get rewritten by dbt every run, so an unfiltered subscription would have
# the pipeline retrigger itself in a loop the moment it wrote its own output.
resource "azurerm_eventgrid_system_topic_event_subscription" "raw_blob_created" {
  name                = "evgs-${var.project_name}-${var.environment}-raw"
  system_topic        = azurerm_eventgrid_system_topic.raw_blob_created.name
  resource_group_name = var.resource_group_name

  included_event_types = ["Microsoft.Storage.BlobCreated"]

  subject_filter {
    subject_begins_with = "/blobServices/default/containers/raw/"
  }

  storage_queue_endpoint {
    storage_account_id = var.storage_account_id
    queue_name         = azurerm_storage_queue.raw_data_events.name
  }
}
