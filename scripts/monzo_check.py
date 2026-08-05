"""Sanity check that the stored refresh token can still mint a working access token."""
import requests

from monzo_auth import get_access_token

headers = {"Authorization": f"Bearer {get_access_token()}"}

whoami = requests.get("https://api.monzo.com/ping/whoami", headers=headers)
whoami.raise_for_status()
print("whoami:", whoami.json())

accounts = requests.get("https://api.monzo.com/accounts", headers=headers)
accounts.raise_for_status()
for account in accounts.json()["accounts"]:
    print(account["id"], account.get("description"))
