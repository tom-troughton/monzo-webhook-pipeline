"""Tracks when the Monzo account holder last interactively consented, so expiry is predictable.

Monzo requires the user to re-approve API access every 90 days. Refreshing the access token does
not reset that clock - only scripts/monzo_oauth.py's authorization-code flow plus the in-app
approval does. When it lapses, the refresh grant keeps succeeding (the token family is fine) but
every data call 403s, so the pipeline dies on a schedule nothing else in the system knows about.
Recording the consent time turns that into a date pipeline_health.yml can warn about in advance.
See docs/decisions/0020-monzo-consent-expiry-warning.md.

Written to `ops/` alongside the reconcile heartbeat, for the same reason: the Event Grid
subscription is subject-filtered to raw/, so nothing here triggers a dbt run.
"""
import json
import os
from datetime import datetime, timezone
from functools import lru_cache

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

CONTAINER = "ops"
BLOB_NAME = "monzo-consent.json"


class MonzoConsentRequired(Exception):
    """Monzo refused account access to a freshly refreshed token - the 90-day consent has lapsed
    (or access was revoked in the app). Not retryable: recovery needs a human to re-run
    scripts/monzo_oauth.py."""


@lru_cache
def _container():
    account_url = f"https://{os.environ['STORAGE_ACCOUNT_NAME']}.blob.core.windows.net"
    client = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())
    return client.get_container_client(CONTAINER)


def record_consent() -> None:
    """Overwrites the consent marker with now. Call only after the user has approved in the Monzo
    app - that approval, not the code exchange, is what starts Monzo's 90-day clock."""
    payload = {"consented_at": datetime.now(timezone.utc).isoformat()}
    _container().upload_blob(BLOB_NAME, json.dumps(payload), overwrite=True)
