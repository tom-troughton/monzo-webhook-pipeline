"""One-off backfill: pulls full transaction history from the Monzo API and writes it to raw/,
using the same write_transaction() the reconciliation Function will eventually use. Manual/local
only, not invoked by CI - see functions/shared/transactions.py for the Function's own
(24h-lookback) equivalent, which this doesn't replace.

Monzo restricts /transactions to the last 90 days unless the access token is under 5 minutes
old (see scripts/monzo_transactions.py) - get_access_token() mints a fresh one each run, so this
gets full history, not just 90 days.
"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "functions"))

from shared.blob_writer import write_transaction
from shared.monzo_auth import get_access_token

PAGE_SIZE = 100


def fetch_all_transactions(headers: dict, account_id: str) -> list[dict]:
    transactions = []
    since = None
    while True:
        params = {"account_id": account_id, "expand[]": "merchant", "limit": PAGE_SIZE}
        if since:
            params["since"] = since
        response = requests.get("https://api.monzo.com/transactions", headers=headers, params=params)
        response.raise_for_status()
        page = response.json()["transactions"]
        if not page:
            break
        transactions.extend(page)
        since = page[-1]["id"]
        if len(page) < PAGE_SIZE:
            break
    return transactions


def main():
    headers = {"Authorization": f"Bearer {get_access_token()}"}

    accounts_response = requests.get("https://api.monzo.com/accounts", headers=headers)
    accounts_response.raise_for_status()

    total = 0
    for account in accounts_response.json()["accounts"]:
        transactions = fetch_all_transactions(headers, account["id"])
        for transaction in transactions:
            write_transaction(transaction, source="reconciliation")
        print(f"{account['id']} ({account.get('description', '?')}): wrote {len(transactions)} transactions")
        total += len(transactions)

    print(f"Total: {total} transactions written to raw/")


if __name__ == "__main__":
    main()
