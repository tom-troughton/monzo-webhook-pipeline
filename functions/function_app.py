import json

import azure.functions as func

from shared.blob_writer import write_transaction
from shared.github_dispatch import trigger_dbt_pipeline
from shared.monzo_auth import get_access_token
from shared.payload_validation import validate_webhook_request
from shared.transactions import fetch_recent_transactions

app = func.FunctionApp()


@app.route(route="webhook/{path_secret}", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
@app.queue_output(arg_name="msg", queue_name="monzo-webhook", connection="AzureWebJobsStorage")
def webhook(req: func.HttpRequest, msg: func.Out[str]) -> func.HttpResponse:
    error = validate_webhook_request(req)
    if error:
        return func.HttpResponse(error, status_code=400)

    msg.set(req.get_body().decode())
    return func.HttpResponse(status_code=200)


@app.queue_trigger(arg_name="msg", queue_name="monzo-webhook", connection="AzureWebJobsStorage")
def raw_writer(msg: func.QueueMessage) -> None:
    event = json.loads(msg.get_body().decode())
    write_transaction(event["data"], source="webhook")


@app.timer_trigger(schedule="0 0 */6 * * *", arg_name="timer", run_on_startup=False)
def reconcile(timer: func.TimerRequest) -> None:
    access_token = get_access_token()
    for transaction in fetch_recent_transactions(access_token):
        write_transaction(transaction, source="reconciliation")


# Fed by an Event Grid subscription delivering to the raw-data-events queue, not a direct
# azure_function_endpoint - that destination type hits a confirmed Azure platform bug with Flex
# Consumption (see docs/decisions/0011). Subject-filtered to the raw/ container at the Event Grid
# subscription level - staging/ and marts/ live on the same storage account and get rewritten by
# dbt every run, so an unfiltered subscription would have the pipeline retrigger itself. The queue
# message content (a Storage BlobCreated event) is irrelevant here - arrival alone is the signal.
@app.queue_trigger(arg_name="msg", queue_name="raw-data-events", connection="AzureWebJobsStorage")
def on_raw_data_created(msg: func.QueueMessage) -> None:
    trigger_dbt_pipeline()
