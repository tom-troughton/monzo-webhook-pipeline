"""Bridges Event Grid to the dbt pipeline. Event Grid can't deliver directly to GitHub's API
(webhook-type subscriptions require a validation handshake GitHub doesn't implement), so this
Function calls repository_dispatch itself - see docs/decisions/0011-event-grid-trigger-for-dbt-pipeline.md.
"""
import os

import requests

from .kv import get_secret

# Event Grid retries a non-2xx delivery, so failing fast on a hung GitHub API call is strictly
# better than holding the Function open until the host kills it.
DISPATCH_TIMEOUT_SECONDS = 30


def trigger_dbt_pipeline() -> None:
    owner = os.environ["GITHUB_REPO_OWNER"]
    repo = os.environ["GITHUB_REPO_NAME"]

    response = requests.post(
        f"https://api.github.com/repos/{owner}/{repo}/dispatches",
        headers={
            "Authorization": f"Bearer {get_secret('github-dispatch-token')}",
            "Accept": "application/vnd.github+json",
        },
        json={"event_type": "raw-data-updated"},
        timeout=DISPATCH_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
