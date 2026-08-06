import json

import azure.functions as func

from shared.blob_writer import write_transaction
from shared.event_grid import validation_response
from shared.github_dispatch import trigger_dbt_pipeline
from shared.monzo_auth import get_access_token
from shared.path_secret import check_path_secret
from shared.payload_validation import validate_webhook_request
from shared.transactions import fetch_recent_transactions

app = func.FunctionApp()


# Writes directly, no queue in between - see docs/decisions/0016. A Storage Queue buffer
# (docs/decisions/0002) originally sat here specifically for automatic retry via a queue trigger,
# but queue triggers turned out to be unreliable on this Flex Consumption app (docs/decisions/0015),
# which made the queue actively worse than no queue: a failed write became a silent, unbounded hang
# instead of a visible failure. Writing directly means a failed write is a failed webhook response,
# which Monzo retries on its own - a real, working retry mechanism - and write_transaction() is
# already idempotent, so retries are harmless either way.
@app.route(route="webhook/{path_secret}", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def webhook(req: func.HttpRequest) -> func.HttpResponse:
    error = validate_webhook_request(req)
    if error:
        return func.HttpResponse(error, status_code=400)

    event = json.loads(req.get_body().decode())
    write_transaction(event["data"], source="webhook")
    return func.HttpResponse(status_code=200)


# Not a native Timer trigger - Flex Consumption doesn't reliably wake a scaled-to-zero app for its
# own schedule (confirmed via App Insights: zero invocations ever, across two missed ticks, only
# resolving on an unrelated manual HTTP request; a known, documented Flex Consumption issue, not
# specific to this app - see docs/decisions/0013). Invoked externally instead, by a GitHub Actions
# scheduled workflow (.github/workflows/reconcile.yml) on the same 6-hourly cadence, so the wake-up
# doesn't depend on Azure's internal scheduler at all.
@app.route(route="reconcile/{path_secret}", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def reconcile(req: func.HttpRequest) -> func.HttpResponse:
    if not check_path_secret(req, "reconcile-trigger-secret"):
        return func.HttpResponse("Not found", status_code=400)

    access_token = get_access_token()
    for transaction in fetch_recent_transactions(access_token):
        write_transaction(transaction, source="reconciliation")

    return func.HttpResponse(status_code=200)


# An HTTP route, not azure_function_endpoint (confirmed Azure platform bug, ADR-0011) or a
# queue_trigger consumed from a Storage Queue (queue-triggered functions have the same Flex
# Consumption scale-to-zero wake-up problem the Timer trigger had - Event Grid delivered every
# event to the queue successfully, but nothing ever consumed them; see ADR-0015). Event Grid's
# webhook_endpoint destination requires echoing back its one-time subscription-validation code -
# see shared/event_grid.py. Subject-filtered to the raw/ container at the Event Grid subscription
# level - staging/ and marts/ live on the same storage account and get rewritten by dbt every run,
# so an unfiltered subscription would have the pipeline retrigger itself.
@app.route(route="on_raw_data_created/{path_secret}", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def on_raw_data_created(req: func.HttpRequest) -> func.HttpResponse:
    if not check_path_secret(req, "event-grid-trigger-secret"):
        return func.HttpResponse("Not found", status_code=400)

    events = req.get_json()
    validation = validation_response(events)
    if validation is not None:
        return func.HttpResponse(json.dumps(validation), status_code=200, mimetype="application/json")

    trigger_dbt_pipeline()
    return func.HttpResponse(status_code=200)
