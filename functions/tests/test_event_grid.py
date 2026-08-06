from shared.event_grid import validation_response


def test_validation_handshake_returns_the_code():
    events = [{
        "eventType": "Microsoft.EventGrid.SubscriptionValidationEvent",
        "data": {"validationCode": "abc-123", "validationUrl": "https://example.com/validate"},
    }]
    assert validation_response(events) == {"validationResponse": "abc-123"}


def test_real_event_returns_none():
    events = [{
        "eventType": "Microsoft.Storage.BlobCreated",
        "subject": "/blobServices/default/containers/raw/blobs/2026/08/06/tx_00001.json",
        "data": {},
    }]
    assert validation_response(events) is None


def test_empty_batch_returns_none():
    assert validation_response([]) is None
