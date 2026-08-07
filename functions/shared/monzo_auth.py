"""Monzo OAuth token exchange, shared by the interactive bootstrap script
(authorization_code grant) and the unattended reconciliation Function
(refresh_token grant). Every exchange rotates and persists the refresh token,
since Monzo invalidates the previous one on use.

Monzo's refresh tokens are single-use and explicitly forbid concurrent refresh
attempts - a second caller presenting an already-rotated token gets the whole
token family invalidated, recoverable only via a full new interactive consent
flow (see docs/decisions/0014). _refresh_lock() enforces that with a blob
lease so overlapping callers wait instead of racing.
"""
import os
import time
from contextlib import contextmanager
from functools import lru_cache

import requests
from azure.core.exceptions import ResourceExistsError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobLeaseClient, BlobServiceClient

from .kv import get_secret, set_secret

REFRESH_LOCK_TIMEOUT_SECONDS = 30
# A hung token exchange is worse than a slow one: it holds the blob lease while it waits, blocking
# every other caller until the 60s lease expires. Nothing here should wait on Monzo indefinitely.
TOKEN_TIMEOUT_SECONDS = 30


@lru_cache
def _lock_blob():
    account_url = f"https://{os.environ['STORAGE_ACCOUNT_NAME']}.blob.core.windows.net"
    client = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())
    return client.get_container_client("locks").get_blob_client("monzo-refresh-token.lock")


@contextmanager
def _refresh_lock():
    lease = BlobLeaseClient(_lock_blob())
    deadline = time.monotonic() + REFRESH_LOCK_TIMEOUT_SECONDS
    while True:
        try:
            lease.acquire(lease_duration=60)
            break
        except ResourceExistsError:
            if time.monotonic() > deadline:
                raise
            time.sleep(2)
    try:
        yield
    finally:
        lease.release()


def _exchange(**grant_params) -> dict:
    response = requests.post("https://api.monzo.com/oauth2/token", data={
        "client_id": get_secret("monzo-client-id"),
        "client_secret": get_secret("monzo-client-secret"),
        **grant_params,
    }, timeout=TOKEN_TIMEOUT_SECONDS)
    response.raise_for_status()
    tokens = response.json()
    set_secret("monzo-refresh-token", tokens["refresh_token"])
    return tokens


def get_access_token() -> str:
    """Refresh grant - used by the reconciliation Function and local scripts."""
    with _refresh_lock():
        tokens = _exchange(grant_type="refresh_token", refresh_token=get_secret("monzo-refresh-token"))
    return tokens["access_token"]


def exchange_authorization_code(code: str, redirect_uri: str) -> None:
    """Authorization-code grant - used only by the interactive bootstrap script."""
    with _refresh_lock():
        _exchange(grant_type="authorization_code", redirect_uri=redirect_uri, code=code)
