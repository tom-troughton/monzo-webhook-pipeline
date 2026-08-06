"""Validates inbound Monzo webhook requests: path secret + payload shape."""
import azure.functions as func

from .path_secret import check_path_secret

REQUIRED_TRANSACTION_FIELDS = ("id", "account_id", "amount", "currency", "created")


def validate_webhook_request(req: func.HttpRequest) -> str | None:
    """Returns an error message if the request should be rejected, else None."""
    if not check_path_secret(req, "webhook-path-secret"):
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
