"""Sanity check that mirrors the reconciliation job's token-refresh pattern:
refresh the access token using Key Vault's stored refresh token, use it,
then save Monzo's rotated refresh token back to Key Vault.
"""
import requests

from kv import get_secret, set_secret

CLIENT_ID = get_secret("monzo-client-id")
CLIENT_SECRET = get_secret("monzo-client-secret")

token_response = requests.post("https://api.monzo.com/oauth2/token", data={
    "grant_type": "refresh_token",
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "refresh_token": get_secret("monzo-refresh-token"),
})
token_response.raise_for_status()
tokens = token_response.json()
set_secret("monzo-refresh-token", tokens["refresh_token"])

headers = {"Authorization": f"Bearer {tokens['access_token']}"}

whoami = requests.get("https://api.monzo.com/ping/whoami", headers=headers)
whoami.raise_for_status()
print("whoami:", whoami.json())

accounts = requests.get("https://api.monzo.com/accounts", headers=headers)
accounts.raise_for_status()
for account in accounts.json()["accounts"]:
    print(account["id"], account.get("description"))
