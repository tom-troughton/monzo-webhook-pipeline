from unittest.mock import patch

import azure.functions as func

from shared.path_secret import check_path_secret


def _request(path_secret):
    return func.HttpRequest(
        method="POST",
        url=f"/api/reconcile/{path_secret}",
        route_params={"path_secret": path_secret},
        body=b"",
    )


@patch("shared.path_secret.get_secret", return_value="correct-secret")
def test_correct_secret_passes(mock_get_secret):
    assert check_path_secret(_request("correct-secret"), "reconcile-trigger-secret") is True
    mock_get_secret.assert_called_once_with("reconcile-trigger-secret")


@patch("shared.path_secret.get_secret", return_value="correct-secret")
def test_wrong_secret_fails(mock_get_secret):
    assert check_path_secret(_request("guessed-secret"), "reconcile-trigger-secret") is False


@patch("shared.path_secret.get_secret", return_value="correct-secret")
def test_missing_secret_fails(mock_get_secret):
    assert check_path_secret(_request(""), "reconcile-trigger-secret") is False
