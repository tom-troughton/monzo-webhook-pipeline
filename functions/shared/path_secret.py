"""Shared path-secret check for HTTP routes that aren't meant to be publicly reachable.
Monzo doesn't sign webhook payloads, and there's no equivalent signing scheme for an
externally-triggered endpoint either, so an unguessable secret in the URL path is the
only proof the caller is who it should be - see docs/decisions.
"""
import hmac

import azure.functions as func

from .kv import get_secret


def check_path_secret(req: func.HttpRequest, secret_name: str) -> bool:
    path_secret = req.route_params.get("path_secret", "")
    return hmac.compare_digest(path_secret, get_secret(secret_name))
