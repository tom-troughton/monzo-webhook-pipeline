"""Fetches Monzo transactions across all accounts for the reconciliation Function.

Pagination lives here rather than being reimplemented per caller: scripts/backfill_transactions.py
walks year-long windows over full history and this module fetches a recent lookback window, but
both need the identical page-following loop. They previously had separate implementations and
only the backfill script's was correct - this one issued a single unpaginated request, silently
capping reconciliation at Monzo's default 100 results per account per run. Silent truncation in
the component ADR-0001 designates as the source of truth is the worst place for it, so there is
now exactly one implementation.
"""
from datetime import datetime, timedelta, timezone

import requests

API_BASE = "https://api.monzo.com"
# Monzo's maximum page size. Also its default, which is what made the missing pagination invisible
# at personal transaction volumes - under 100 results in the window, one request returns everything.
PAGE_SIZE = 100
# No unattended HTTP call should be able to hang indefinitely: on Flex Consumption that burns the
# execution budget, and inside get_access_token() it does so while holding the refresh lease.
TIMEOUT_SECONDS = 30


def fetch_accounts(headers: dict) -> list[dict]:
    response = requests.get(f"{API_BASE}/accounts", headers=headers, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()["accounts"]


def fetch_account_transactions(
    headers: dict, account_id: str, since: str, before: str | None = None
) -> list[dict]:
    """Every transaction for one account in the given window, following Monzo's pagination.

    Monzo caps a response at `limit` and returns no "more results" flag, so the only safe stop
    condition is a short page - a full page means "there may be more". `since` doubles as the
    cursor: given a transaction ID rather than a timestamp it means "everything after this one".
    """
    transactions: list[dict] = []
    cursor = since

    while True:
        params = {
            "account_id": account_id,
            "expand[]": "merchant",
            "limit": PAGE_SIZE,
            "since": cursor,
        }
        if before is not None:
            params["before"] = before

        response = requests.get(
            f"{API_BASE}/transactions", headers=headers, params=params, timeout=TIMEOUT_SECONDS
        )
        response.raise_for_status()

        page = response.json()["transactions"]
        if not page:
            break

        transactions.extend(page)
        if len(page) < PAGE_SIZE:
            break

        cursor = page[-1]["id"]

    return transactions


def fetch_recent_transactions(access_token: str, lookback_hours: int = 24) -> list[dict]:
    headers = {"Authorization": f"Bearer {access_token}"}

    # lookback_hours > the 6-hourly schedule so a missed run still gets fully caught up next time.
    since = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()

    transactions = []
    for account in fetch_accounts(headers):
        transactions.extend(fetch_account_transactions(headers, account["id"], since))

    return transactions
