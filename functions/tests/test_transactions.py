from unittest.mock import MagicMock, patch

from shared.transactions import PAGE_SIZE, fetch_account_transactions, fetch_recent_transactions


def _page(transactions):
    return MagicMock(json=lambda: {"transactions": transactions})


def _accounts(*account_ids):
    return MagicMock(json=lambda: {"accounts": [{"id": a} for a in account_ids]})


def _transactions(count, prefix="tx"):
    return [{"id": f"{prefix}_{i:05d}"} for i in range(count)]


def test_follows_pagination_past_the_first_page():
    """The bug this guards: a single unpaginated request silently capped reconciliation at
    Monzo's default page size, dropping everything beyond it without erroring."""
    with patch("shared.transactions.requests.get") as mock_get:
        mock_get.side_effect = [
            _page(_transactions(PAGE_SIZE, "a")),
            _page(_transactions(PAGE_SIZE, "b")),
            _page(_transactions(7, "c")),
        ]
        transactions = fetch_account_transactions({}, "acc_1", since="2026-08-01T00:00:00+00:00")

    assert len(transactions) == PAGE_SIZE * 2 + 7
    assert mock_get.call_count == 3


def test_stops_on_a_short_page_without_an_extra_request():
    with patch("shared.transactions.requests.get") as mock_get:
        mock_get.side_effect = [_page(_transactions(3))]
        transactions = fetch_account_transactions({}, "acc_1", since="2026-08-01T00:00:00+00:00")

    assert len(transactions) == 3
    assert mock_get.call_count == 1


def test_uses_the_last_transaction_id_as_the_next_cursor():
    """Monzo's `since` doubles as a cursor when given a transaction ID - paging by anything else
    (an offset, a repeated timestamp) would loop on the same page forever."""
    with patch("shared.transactions.requests.get") as mock_get:
        mock_get.side_effect = [_page(_transactions(PAGE_SIZE, "a")), _page([])]
        fetch_account_transactions({}, "acc_1", since="2026-08-01T00:00:00+00:00")

    first, second = mock_get.call_args_list
    assert first.kwargs["params"]["since"] == "2026-08-01T00:00:00+00:00"
    assert second.kwargs["params"]["since"] == f"a_{PAGE_SIZE - 1:05d}"


def test_requests_expanded_merchant_and_a_full_page():
    """expand[]=merchant is required for the dbt schema - omitting it once already broke
    stg_transactions' merchant columns."""
    with patch("shared.transactions.requests.get") as mock_get:
        mock_get.side_effect = [_page([])]
        fetch_account_transactions({}, "acc_1", since="2026-08-01T00:00:00+00:00")

    params = mock_get.call_args.kwargs["params"]
    assert params["expand[]"] == "merchant"
    assert params["limit"] == PAGE_SIZE
    assert "before" not in params


def test_before_is_only_sent_when_given():
    with patch("shared.transactions.requests.get") as mock_get:
        mock_get.side_effect = [_page([])]
        fetch_account_transactions(
            {}, "acc_1", since="2026-08-01T00:00:00+00:00", before="2026-08-02T00:00:00+00:00"
        )

    assert mock_get.call_args.kwargs["params"]["before"] == "2026-08-02T00:00:00+00:00"


def test_every_outbound_call_sets_a_timeout():
    """An unattended call with no timeout can hang until the Functions host kills it."""
    with patch("shared.transactions.requests.get") as mock_get:
        mock_get.side_effect = [_accounts("acc_1"), _page([])]
        fetch_recent_transactions("access-token")

    assert all(call.kwargs.get("timeout") for call in mock_get.call_args_list)


def test_fetches_across_every_account():
    with patch("shared.transactions.requests.get") as mock_get:
        mock_get.side_effect = [
            _accounts("acc_1", "acc_2"),
            _page(_transactions(2, "one")),
            _page(_transactions(3, "two")),
        ]
        transactions = fetch_recent_transactions("access-token")

    assert len(transactions) == 5
    queried = [c.kwargs["params"]["account_id"] for c in mock_get.call_args_list[1:]]
    assert queried == ["acc_1", "acc_2"]
