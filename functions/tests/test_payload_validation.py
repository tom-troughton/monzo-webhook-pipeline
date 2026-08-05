import json
from unittest.mock import patch

import azure.functions as func

from shared.payload_validation import validate_webhook_request

VALID_TRANSACTION = {
    "id": "tx_00001",
    "account_id": "acc_00001",
    "amount": -100,
    "currency": "GBP",
    "created": "2026-01-01T00:00:00Z",
}


def _request(path_secret="correct-secret", body=b""):
    return func.HttpRequest(
        method="POST",
        url=f"/api/webhook/{path_secret}",
        route_params={"path_secret": path_secret},
        body=body,
    )


@patch("shared.payload_validation.get_secret", return_value="correct-secret")
def test_valid_transaction_created_payload_is_accepted(mock_get_secret):
    body = json.dumps({"type": "transaction.created", "data": VALID_TRANSACTION}).encode()
    assert validate_webhook_request(_request(body=body)) is None


@patch("shared.payload_validation.get_secret", return_value="correct-secret")
def test_wrong_path_secret_is_rejected(mock_get_secret):
    body = json.dumps({"type": "transaction.created", "data": VALID_TRANSACTION}).encode()
    error = validate_webhook_request(_request(path_secret="guessed-secret", body=body))
    assert error == "Not found"


@patch("shared.payload_validation.get_secret", return_value="correct-secret")
def test_invalid_json_is_rejected(mock_get_secret):
    error = validate_webhook_request(_request(body=b"not json"))
    assert error == "Invalid JSON"


@patch("shared.payload_validation.get_secret", return_value="correct-secret")
def test_unsupported_event_type_is_rejected(mock_get_secret):
    body = json.dumps({"type": "transaction.updated", "data": VALID_TRANSACTION}).encode()
    error = validate_webhook_request(_request(body=body))
    assert error == "Unsupported event type"


@patch("shared.payload_validation.get_secret", return_value="correct-secret")
def test_missing_required_field_is_rejected(mock_get_secret):
    incomplete = {k: v for k, v in VALID_TRANSACTION.items() if k != "amount"}
    body = json.dumps({"type": "transaction.created", "data": incomplete}).encode()
    error = validate_webhook_request(_request(body=body))
    assert error == "Missing fields: amount"
