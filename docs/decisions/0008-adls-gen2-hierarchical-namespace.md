# 0008. Enable ADLS Gen2 hierarchical namespace on the storage account

Status: Proposed
Date: 2026-08-04

## Context

Blob Storage has a flat namespace — `raw/2026/08/04/tx_00123.json` is one blob with a name
containing slashes, not a real nested directory. Listing tools fake the folder view via prefix
delimiters. Azure Data Lake Storage Gen2 (hierarchical namespace enabled on the same storage
account type) makes directories real objects, with atomic directory rename/move, per-directory
ACLs, and better listing/partition-pruning performance — relevant since dbt/DuckDB will be reading
Hive-partitioned Parquet out of `staging/` and `marts/`.

## Decision

Not yet made. Proposed: set `is_hns_enabled = true` on the `azurerm_storage_account` resource before
any data is written, since enabling it later on an existing storage account is not supported.

## Consequences (if accepted)

- No change to Blob-API compatibility or pricing tier; still Standard performance.
- Slightly different transaction pricing category for some operations (directory-level ops use the
  Data Lake API) — negligible at this data volume.
- Must be decided *before* provisioning real data into the storage account, since it can't be
  toggled on retroactively — this is the deciding factor for resolving this ADR soon rather than
  deferring indefinitely.
