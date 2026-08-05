from unittest.mock import MagicMock, patch

from shared.blob_writer import write_transaction

TRANSACTION = {
    "id": "tx_00001",
    "created": "2026-01-15T09:30:00Z",
}


def test_write_transaction_names_blob_by_date_and_id():
    mock_container = MagicMock()
    with patch("shared.blob_writer._container", return_value=mock_container):
        write_transaction(TRANSACTION, source="webhook")

    call = mock_container.upload_blob.call_args
    assert call.args[0] == "2026/01/15/tx_00001.json"
    assert call.kwargs["overwrite"] is True


def test_redelivered_transaction_overwrites_the_same_blob():
    mock_container = MagicMock()
    with patch("shared.blob_writer._container", return_value=mock_container):
        write_transaction(TRANSACTION, source="webhook")
        write_transaction(TRANSACTION, source="reconciliation")

    first_call, second_call = mock_container.upload_blob.call_args_list
    assert first_call.args[0] == second_call.args[0]
