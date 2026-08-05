from unittest.mock import MagicMock, patch

from shared import monzo_auth

SECRETS = {
    "monzo-client-id": "client-id",
    "monzo-client-secret": "client-secret",
    "monzo-refresh-token": "old-refresh-token",
}


@patch("shared.monzo_auth.set_secret")
@patch("shared.monzo_auth.get_secret", side_effect=SECRETS.__getitem__)
@patch("shared.monzo_auth.requests.post")
def test_get_access_token_rotates_refresh_token(mock_post, mock_get_secret, mock_set_secret):
    mock_post.return_value = MagicMock(json=lambda: {
        "access_token": "new-access-token",
        "refresh_token": "new-refresh-token",
    })

    token = monzo_auth.get_access_token()

    assert token == "new-access-token"
    mock_set_secret.assert_called_once_with("monzo-refresh-token", "new-refresh-token")
    assert mock_post.call_args.kwargs["data"]["grant_type"] == "refresh_token"
    assert mock_post.call_args.kwargs["data"]["refresh_token"] == "old-refresh-token"


@patch("shared.monzo_auth.set_secret")
@patch("shared.monzo_auth.get_secret", side_effect=SECRETS.__getitem__)
@patch("shared.monzo_auth.requests.post")
def test_exchange_authorization_code_persists_rotated_refresh_token(mock_post, mock_get_secret, mock_set_secret):
    mock_post.return_value = MagicMock(json=lambda: {
        "access_token": "new-access-token",
        "refresh_token": "new-refresh-token",
    })

    monzo_auth.exchange_authorization_code("auth-code", "http://localhost:5000/callback")

    mock_set_secret.assert_called_once_with("monzo-refresh-token", "new-refresh-token")
    assert mock_post.call_args.kwargs["data"]["grant_type"] == "authorization_code"
    assert mock_post.call_args.kwargs["data"]["code"] == "auth-code"
