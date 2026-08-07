"""Writes transaction records to raw/, named deterministically by transaction_id
so redelivery (webhook retries, reconciliation overlap) is naturally idempotent -
see docs/decisions/0002-storage-queue-buffer.md.

Because the blob name is derived from transaction_id alone, there is exactly one blob per
transaction and writes are last-writer-wins. That makes this the only place ADR-0001's
"reconciliation is authoritative over the webhook" rule can actually be enforced: the dedupe
tie-break in dbt's stg_transactions can never fire, since two rows for one transaction_id would
require two blobs. A retried webhook delivery arriving after reconciliation had already written
the same transaction would otherwise silently replace the authoritative record with the
notification one.
"""
import json
import logging
import os
from datetime import datetime
from functools import lru_cache

from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

RECONCILIATION = "reconciliation"


@lru_cache
def _container():
    account_url = f"https://{os.environ['STORAGE_ACCOUNT_NAME']}.blob.core.windows.net"
    client = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())
    return client.get_container_client("raw")


def _existing_source(blob_name: str) -> str | None:
    """The `source` of an already-written blob, or None if it doesn't exist.

    Reads blob metadata (a HEAD request), not the blob body - this runs on the webhook's hot path
    and only needs one field. Blobs written before this metadata existed (the one-off historical
    backfill) return None and are treated as overwritable; they're old transactions that will
    never receive a webhook, so the distinction can't arise for them in practice.
    """
    try:
        properties = _container().get_blob_client(blob_name).get_blob_properties()
    except ResourceNotFoundError:
        return None
    return (properties.metadata or {}).get("source")


def write_transaction(transaction: dict, source: str) -> None:
    created = datetime.fromisoformat(transaction["created"].replace("Z", "+00:00"))
    blob_name = f"{created:%Y/%m/%d}/{transaction['id']}.json"

    # Reconciliation always wins (ADR-0001), so it never needs to check; only a webhook write has
    # to yield. Skipping is correct rather than a lost write - the transaction is already in raw/,
    # in its more authoritative form, so the caller's 200 to Monzo is still honest.
    if source != RECONCILIATION and _existing_source(blob_name) == RECONCILIATION:
        logging.info("Skipping %s write for %s - reconciled copy already present", source, blob_name)
        return

    payload = {"source": source, "transaction": transaction}
    _container().upload_blob(
        blob_name,
        json.dumps(payload),
        overwrite=True,
        # Mirrors the `source` in the body so precedence can be checked without a full download.
        metadata={"source": source},
    )
