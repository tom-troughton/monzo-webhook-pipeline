import json
from unittest.mock import MagicMock, patch

import pytest

from shared.blob_writer import write_transaction

TRANSACTION = {
    "id": "tx_00001",
    "created": "2026-01-15T09:30:00Z",
}


@pytest.fixture
def container():
    """Container double with no pre-existing blob, unless a test says otherwise via
    `existing_source`."""
    mock_container = MagicMock()
    with patch("shared.blob_writer._container", return_value=mock_container), patch(
        "shared.blob_writer._existing_source", return_value=None
    ):
        yield mock_container


def test_names_blob_by_date_and_id(container):
    write_transaction(TRANSACTION, source="webhook")

    call = container.upload_blob.call_args
    assert call.args[0] == "2026/01/15/tx_00001.json"
    assert call.kwargs["overwrite"] is True


def test_redelivered_transaction_targets_the_same_blob(container):
    write_transaction(TRANSACTION, source="webhook")
    write_transaction(TRANSACTION, source="reconciliation")

    first_call, second_call = container.upload_blob.call_args_list
    assert first_call.args[0] == second_call.args[0]


def test_records_source_in_body_and_metadata(container):
    write_transaction(TRANSACTION, source="reconciliation")

    call = container.upload_blob.call_args
    assert json.loads(call.args[1])["source"] == "reconciliation"
    # Metadata mirrors it so precedence can be checked with a HEAD, not a full download.
    assert call.kwargs["metadata"] == {"source": "reconciliation"}


def test_webhook_does_not_clobber_an_already_reconciled_transaction():
    """ADR-0001 makes reconciliation authoritative. One blob per transaction_id means raw/ is
    last-writer-wins, so this is the only place that rule can be enforced - dbt's dedupe
    tie-break can never fire on data that only ever produces one row."""
    mock_container = MagicMock()
    with patch("shared.blob_writer._container", return_value=mock_container), patch(
        "shared.blob_writer._existing_source", return_value="reconciliation"
    ):
        write_transaction(TRANSACTION, source="webhook")

    mock_container.upload_blob.assert_not_called()


def test_reconciliation_overwrites_an_existing_webhook_write():
    mock_container = MagicMock()
    with patch("shared.blob_writer._container", return_value=mock_container), patch(
        "shared.blob_writer._existing_source", return_value="webhook"
    ):
        write_transaction(TRANSACTION, source="reconciliation")

    assert mock_container.upload_blob.call_args.kwargs["metadata"] == {"source": "reconciliation"}


def test_webhook_overwrites_an_existing_webhook_write():
    """Monzo retries a failed delivery; a retry must still land rather than being mistaken for a
    precedence conflict."""
    mock_container = MagicMock()
    with patch("shared.blob_writer._container", return_value=mock_container), patch(
        "shared.blob_writer._existing_source", return_value="webhook"
    ):
        write_transaction(TRANSACTION, source="webhook")

    mock_container.upload_blob.assert_called_once()


def test_missing_blob_reports_no_existing_source():
    """Blobs from the historical backfill predate the metadata, and a genuinely absent blob is the
    common case - neither should raise on the webhook hot path."""
    from azure.core.exceptions import ResourceNotFoundError

    from shared.blob_writer import _existing_source

    mock_container = MagicMock()
    mock_container.get_blob_client.return_value.get_blob_properties.side_effect = (
        ResourceNotFoundError("nope")
    )
    with patch("shared.blob_writer._container", return_value=mock_container):
        assert _existing_source("2026/01/15/tx_00001.json") is None
