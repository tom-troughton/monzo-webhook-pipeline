"""Writes transaction records to raw/, named deterministically by transaction_id
so redelivery (webhook retries, reconciliation overlap) is naturally idempotent -
see docs/decisions/0002-storage-queue-buffer.md.
"""
import json
import os
from datetime import datetime
from functools import lru_cache

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient


@lru_cache
def _container():
    account_url = f"https://{os.environ['STORAGE_ACCOUNT_NAME']}.blob.core.windows.net"
    client = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())
    return client.get_container_client("raw")


def write_transaction(transaction: dict, source: str) -> None:
    created = datetime.fromisoformat(transaction["created"].replace("Z", "+00:00"))
    blob_name = f"{created:%Y/%m/%d}/{transaction['id']}.json"

    payload = {"source": source, "transaction": transaction}
    _container().upload_blob(blob_name, json.dumps(payload), overwrite=True)
