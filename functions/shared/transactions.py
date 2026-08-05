"""Fetches Monzo transactions across all accounts for the reconciliation Function."""
from datetime import datetime, timedelta, timezone

import requests


def fetch_recent_transactions(access_token: str, lookback_hours: int = 24) -> list[dict]:
    headers = {"Authorization": f"Bearer {access_token}"}

    accounts_response = requests.get("https://api.monzo.com/accounts", headers=headers)
    accounts_response.raise_for_status()

    # lookback_hours > the 6-hourly schedule so a missed run still gets fully caught up next time.
    since = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()

    transactions = []
    for account in accounts_response.json()["accounts"]:
        response = requests.get(
            "https://api.monzo.com/transactions",
            headers=headers,
            params={"account_id": account["id"], "since": since},
        )
        response.raise_for_status()
        transactions.extend(response.json()["transactions"])

    return transactions
