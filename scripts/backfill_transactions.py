"""One-off backfill: pulls full transaction history from the Monzo API and writes it to raw/,
using the same write_transaction() the reconciliation Function uses. Manual/local only, not
invoked by CI - see functions/shared/transactions.py for the Function's own (24h-lookback)
equivalent, which this doesn't replace. Page-following is shared with that module rather than
duplicated here; only the year-long windowing below is specific to backfilling.

Two separate Monzo API constraints, easy to conflate:
1. A single /transactions call can't span more than 365 days (`since`..`before`), or it 400s with
   `bad_request.invalid_time_range` - so full history has to be walked in year-long windows, not
   fetched in one call regardless of how far back `since` is set.
2. Accessing transactions outside the normal recent window at all requires the user to have
   *interactively* re-authorised very recently (403 `forbidden.verification_required` otherwise) -
   refreshing the access token via the refresh_token grant does NOT satisfy this, only completing
   scripts/monzo_oauth.py's authorization-code flow does (including the "approve in the Monzo app"
   step it prompts for). Run that immediately before this script if backfilling older history.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "functions"))

from shared.blob_writer import write_transaction
from shared.monzo_auth import get_access_token
from shared.transactions import fetch_account_transactions, fetch_accounts

MAX_WINDOW_DAYS = 365


def fetch_all_transactions(headers: dict, account_id: str, account_created: str) -> list[dict]:
    transactions = []
    window_start = datetime.fromisoformat(account_created.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    while window_start < now:
        window_end = min(window_start + timedelta(days=MAX_WINDOW_DAYS), now)
        # Paginated page-following lives in shared/transactions.py, shared with the reconciliation
        # Function - this script only adds the year-long windowing that constraint 1 above forces.
        transactions.extend(fetch_account_transactions(
            headers, account_id, window_start.isoformat(), before=window_end.isoformat()
        ))
        window_start = window_end
    return transactions


def main():
    headers = {"Authorization": f"Bearer {get_access_token()}"}

    total = 0
    for account in fetch_accounts(headers):
        transactions = fetch_all_transactions(headers, account["id"], account["created"])
        for transaction in transactions:
            write_transaction(transaction, source="reconciliation")
        print(f"{account['id']} ({account.get('description', '?')}): wrote {len(transactions)} transactions")
        total += len(transactions)

    print(f"Total: {total} transactions written to raw/")


if __name__ == "__main__":
    main()
