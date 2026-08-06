from unittest.mock import patch

import pytest

from shared.github_dispatch import trigger_dbt_pipeline


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("GITHUB_REPO_OWNER", "tom-troughton")
    monkeypatch.setenv("GITHUB_REPO_NAME", "monzo-webhook-pipeline")


def test_dispatches_to_the_configured_repo_with_the_expected_event_type():
    with patch("shared.github_dispatch.get_secret", return_value="fake-token"), patch(
        "shared.github_dispatch.requests.post"
    ) as mock_post:
        mock_post.return_value.raise_for_status.return_value = None
        trigger_dbt_pipeline()

    call = mock_post.call_args
    assert call.args[0] == "https://api.github.com/repos/tom-troughton/monzo-webhook-pipeline/dispatches"
    assert call.kwargs["json"] == {"event_type": "raw-data-updated"}
    assert call.kwargs["headers"]["Authorization"] == "Bearer fake-token"


def test_raises_on_a_failed_dispatch():
    with patch("shared.github_dispatch.get_secret", return_value="fake-token"), patch(
        "shared.github_dispatch.requests.post"
    ) as mock_post:
        mock_post.return_value.raise_for_status.side_effect = Exception("boom")
        with pytest.raises(Exception, match="boom"):
            trigger_dbt_pipeline()
