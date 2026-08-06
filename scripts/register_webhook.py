"""Registers this deployment's webhook URL with Monzo, for every account.
Monzo doesn't dedupe registrations by URL, so this checks existing webhooks first and skips
accounts that already have this exact URL registered, rather than creating duplicates on rerun.
"""
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "functions"))

from shared.kv import get_secret
from shared.monzo_auth import get_access_token

headers = {"Authorization": f"Bearer {get_access_token()}"}
webhook_url = f"https://{os.environ['FUNCTION_APP_HOSTNAME']}/api/webhook/{get_secret('webhook-path-secret')}"

accounts = requests.get("https://api.monzo.com/accounts", headers=headers)
accounts.raise_for_status()

for account in accounts.json()["accounts"]:
    account_id = account["id"]

    existing = requests.get(
        "https://api.monzo.com/webhooks", headers=headers, params={"account_id": account_id}
    )
    existing.raise_for_status()
    if any(w["url"] == webhook_url for w in existing.json()["webhooks"]):
        print(f"{account_id} ({account.get('description', '?')}): already registered, skipping")
        continue

    response = requests.post(
        "https://api.monzo.com/webhooks",
        headers=headers,
        data={"account_id": account_id, "url": webhook_url},
    )
    response.raise_for_status()
    webhook = response.json()["webhook"]
    print(f"{account_id} ({account.get('description', '?')}): registered webhook {webhook['id']}")
