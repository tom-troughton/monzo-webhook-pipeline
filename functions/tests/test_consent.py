import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from shared.consent import BLOB_NAME, record_consent


def test_records_consent_time_as_timezone_aware_utc():
    """pipeline_health.yml parses this with `date -u -d` to compute the consent's age - a naive
    timestamp would be read as runner-local and skew the expiry warning."""
    mock_container = MagicMock()
    with patch("shared.consent._container", return_value=mock_container):
        record_consent()

    call = mock_container.upload_blob.call_args
    assert call.args[0] == BLOB_NAME
    assert call.kwargs["overwrite"] is True
    parsed = datetime.fromisoformat(json.loads(call.args[1])["consented_at"])
    assert parsed.utcoffset() == timezone.utc.utcoffset(None)
