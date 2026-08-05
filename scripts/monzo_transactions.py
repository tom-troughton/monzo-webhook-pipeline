"""Fetch recent transactions for the first Monzo account."""
import requests

from monzo_auth import get_access_token

headers = {"Authorization": f"Bearer {get_access_token()}"}

accounts = requests.get("https://api.monzo.com/accounts", headers=headers)
accounts.raise_for_status()
account_id = accounts.json()["accounts"][0]["id"]

# Non-whitelisted clients only get unrestricted history in the 5 minutes after
# authenticating; outside that window Monzo limits /transactions to the last 90 days.
transactions = requests.get(
    "https://api.monzo.com/transactions",
    headers=headers,
    params={"account_id": account_id, "expand[]": "merchant"},
)
transactions.raise_for_status()

for txn in transactions.json()["transactions"]:
    print(txn["created"], round(txn["amount"] / 100, 2), txn["currency"], txn.get("description"))
