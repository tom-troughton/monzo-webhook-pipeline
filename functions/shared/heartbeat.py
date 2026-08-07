"""Records that reconciliation actually ran, so a dead ingestion path is detectable.

Without this there is no ingestion-run signal anywhere in the system - only transaction data,
which can't distinguish "the pipeline is broken" from "no money was spent this week". That
ambiguity is why a plain freshness check on max(created_at) isn't good enough on its own: a
quiet week and a revoked Monzo refresh token look identical. A heartbeat separates them, because
reconcile writes one on every successful run whether it found transactions or not.

Written to the `ops` container, deliberately not `raw/`: the Event Grid subscription is
subject-filtered to raw/, so a heartbeat there would dispatch a full dbt run every 6 hours for
no reason. See docs/decisions/0017-reconciliation-heartbeat-blob.md.
"""
import json
import os
from datetime import datetime, timezone
from functools import lru_cache

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

CONTAINER = "ops"
BLOB_NAME = "reconcile-heartbeat.json"


@lru_cache
def _container():
    account_url = f"https://{os.environ['STORAGE_ACCOUNT_NAME']}.blob.core.windows.net"
    client = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())
    return client.get_container_client(CONTAINER)


def record_reconcile_run(transactions_written: int) -> None:
    """Overwrites the single heartbeat blob with this run's outcome.

    Only the most recent run is kept - this answers "is ingestion alive", not "what happened
    historically", which is what Application Insights is for. Call this only after the run has
    fully succeeded: a partial run that raises must leave the previous (now stale) heartbeat in
    place, so the staleness check in .github/workflows/pipeline_health.yml can see the failure.
    """
    payload = {
        "last_run_at": datetime.now(timezone.utc).isoformat(),
        "transactions_written": transactions_written,
    }
    _container().upload_blob(BLOB_NAME, json.dumps(payload), overwrite=True)
