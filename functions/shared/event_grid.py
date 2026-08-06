"""Event Grid webhook-endpoint validation handshake. Event Grid POSTs a
SubscriptionValidationEvent once, at subscription-creation time, and expects
the validation code echoed back within the response for the subscription to
be confirmed - a generic Webhook destination gets no other exemption from
this, unlike the first-party destination types (Function, Storage Queue, ...).
See docs/decisions/0015-event-grid-webhook-endpoint.md.
"""

VALIDATION_EVENT_TYPE = "Microsoft.EventGrid.SubscriptionValidationEvent"


def validation_response(events: list[dict]) -> dict | None:
    """Returns the {"validationResponse": ...} body if this batch is a subscription
    validation handshake, else None (meaning: real event(s) to act on)."""
    for event in events:
        if event.get("eventType") == VALIDATION_EVENT_TYPE:
            return {"validationResponse": event["data"]["validationCode"]}
    return None
