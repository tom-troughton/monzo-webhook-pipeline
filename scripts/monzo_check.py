"""Sanity check: confirm the stored access token can see real account data."""
import os

import requests
from dotenv import load_dotenv

ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(ENV_PATH)

headers = {"Authorization": f"Bearer {os.environ['MONZO_ACCESS_TOKEN']}"}

whoami = requests.get("https://api.monzo.com/ping/whoami", headers=headers)
whoami.raise_for_status()
print("whoami:", whoami.json())

accounts = requests.get("https://api.monzo.com/accounts", headers=headers)
accounts.raise_for_status()
for account in accounts.json()["accounts"]:
    print(account["id"], account.get("description"))
