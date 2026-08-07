import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from shared.heartbeat import BLOB_NAME, record_reconcile_run


def _recorded_payload(mock_container):
    call = mock_container.upload_blob.call_args
    return call.args[0], json.loads(call.args[1]), call.kwargs


def test_records_run_to_the_single_heartbeat_blob():
    mock_container = MagicMock()
    with patch("shared.heartbeat._container", return_value=mock_container):
        record_reconcile_run(7)

    name, payload, kwargs = _recorded_payload(mock_container)
    assert name == BLOB_NAME
    assert payload["transactions_written"] == 7
    # Overwritten rather than appended - this answers "is ingestion alive", not "what happened
    # historically" (that's Application Insights).
    assert kwargs["overwrite"] is True


def test_a_run_that_found_no_transactions_still_records_a_heartbeat():
    """The whole reason this is a heartbeat and not a max(created_at) freshness check: a quiet
    week of spending must not look like a dead pipeline."""
    mock_container = MagicMock()
    with patch("shared.heartbeat._container", return_value=mock_container):
        record_reconcile_run(0)

    _, payload, _ = _recorded_payload(mock_container)
    assert payload["transactions_written"] == 0


def test_last_run_at_is_timezone_aware_utc():
    """pipeline_health.yml parses this with `date -u -d` to compute an age in hours - a naive
    timestamp would be read as runner-local and silently skew the staleness check."""
    mock_container = MagicMock()
    with patch("shared.heartbeat._container", return_value=mock_container):
        record_reconcile_run(1)

    _, payload, _ = _recorded_payload(mock_container)
    parsed = datetime.fromisoformat(payload["last_run_at"])
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timezone.utc.utcoffset(None)
