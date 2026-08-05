# 0008. Do not enable ADLS Gen2 hierarchical namespace

Status: Rejected
Date: 2026-08-05

## Context

Blob Storage has a flat namespace — `raw/2026/08/04/tx_00123.json` is one blob with a name
containing slashes, not a real nested directory; listing tools fake the folder view via prefix
delimiters. Azure Data Lake Storage Gen2 (hierarchical namespace enabled on the same storage account
type) makes directories real objects, with atomic directory rename/move, per-directory ACLs, and
faster metadata operations at large object counts.

This was originally proposed on the assumption that dbt/DuckDB reading Hive-partitioned Parquet out
of `staging/`/`marts/` needed it. That assumption doesn't hold: DuckDB's `azure` extension reads
Blob Storage via prefix-based listing and parses `key=value` hive-partition segments directly out of
flat blob names — it never depends on directories being real objects. The same is true of Apache
Iceberg (considered separately as a table-format option): it's storage-backend-agnostic and doesn't
require HNS either. Neither DuckDB nor Iceberg is the justification HNS needed.

The genuine benefits of HNS — atomic directory rename, per-directory ACLs, faster listing at scale —
don't apply here: there's a single sequential writer (GitHub Actions running dbt), no concurrent
writers needing directory-level atomicity, and object counts nowhere near where listing performance
would matter.

## Decision

Do not enable hierarchical namespace. Keep the storage account as plain Blob Storage (Standard,
flat namespace), as already provisioned.

## Consequences

- No HNS-related complexity or transaction-pricing nuance to reason about.
- Revisit only if a concrete need shows up later — e.g. multiple concurrent writers requiring
  directory-level atomicity, or per-directory ACLs becoming necessary for access control. Since HNS
  cannot be enabled retroactively on an existing storage account, that would mean provisioning a new
  account and migrating data, not a config flip.
