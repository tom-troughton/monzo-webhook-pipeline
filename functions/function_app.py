import json

import azure.functions as func

from shared.blob_writer import write_transaction
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
