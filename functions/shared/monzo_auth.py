"""Monzo OAuth token exchange, shared by the interactive bootstrap script
(authorization_code grant) and the unattended reconciliation Function
(refresh_token grant). Every exchange rotates and persists the refresh token,
since Monzo invalidates the previous one on use.
"""
import requests

from .kv import get_secret, set_secret


def _request_tokens(**grant_params) -> dict:
    response = requests.post("https://api.monzo.com/oauth2/token", data={
        "client_id": get_secret("monzo-client-id"),
        "client_secret": get_secret("monzo-client-secret"),
        **grant_params,
    })
    response.raise_for_status()
    tokens = response.json()
    set_secret("monzo-refresh-token", tokens["refresh_token"])
    return tokens


def get_access_token() -> str:
    """Refresh grant - used by the reconciliation Function and local scripts."""
    tokens = _request_tokens(grant_type="refresh_token", refresh_token=get_secret("monzo-refresh-token"))
    return tokens["access_token"]


def exchange_authorization_code(code: str, redirect_uri: str) -> None:
    """Authorization-code grant - used only by the interactive bootstrap script."""
    _request_tokens(grant_type="authorization_code", redirect_uri=redirect_uri, code=code)
