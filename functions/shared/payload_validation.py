"""Validates inbound Monzo webhook requests: path secret + payload shape.
Monzo doesn't sign webhook payloads, so the path secret is the only proof the
caller is actually Monzo - see docs/decisions and the spec's Ingestion section.
"""
import hmac

import azure.functions as func

from .kv import get_secret

REQUIRED_TRANSACTION_FIELDS = ("id", "account_id", "amount", "currency", "created")


def validate_webhook_request(req: func.HttpRequest) -> str | None:
    """Returns an error message if the request should be rejected, else None."""
    path_secret = req.route_params.get("path_secret", "")
    if not hmac.compare_digest(path_secret, get_secret("webhook-path-secret")):
        return "Not found"

    try:
        body = req.get_json()
    except ValueError:
        return "Invalid JSON"

    if body.get("type") != "transaction.created":
        return "Unsupported event type"

    data = body.get("data", {})
    missing = [field for field in REQUIRED_TRANSACTION_FIELDS if field not in data]
    if missing:
        return f"Missing fields: {', '.join(missing)}"

    return None
