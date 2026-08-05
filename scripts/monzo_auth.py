"""Refresh the Monzo access token using the refresh token stored in Key Vault,
saving Monzo's rotated refresh token back to Key Vault.
"""
import requests

from kv import get_secret, set_secret


def get_access_token() -> str:
    client_id = get_secret("monzo-client-id")
    client_secret = get_secret("monzo-client-secret")

    response = requests.post("https://api.monzo.com/oauth2/token", data={
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": get_secret("monzo-refresh-token"),
    })
    response.raise_for_status()
    tokens = response.json()
    set_secret("monzo-refresh-token", tokens["refresh_token"])
    return tokens["access_token"]
