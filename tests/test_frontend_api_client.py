from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import httpx
import pytest
import streamlit as st

import frontend.api_client as api_client


def _response(payload):
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


@pytest.fixture()
def http():
    """A fake httpx.Client, with the module's reused client and the read cache both reset so
    each test starts cold."""
    api_client._client.cache_clear()
    st.cache_data.clear()
    fake = MagicMock()
    fake.get.return_value = _response({"ok": True})
    fake.patch.return_value = _response({"ok": True})
    with patch("frontend.api_client.httpx.Client", return_value=fake) as client_cls:
        yield fake, client_cls
    api_client._client.cache_clear()
    st.cache_data.clear()


def test_reuses_one_http_client_across_calls(http):
    # P1 (docs/next-steps.md): building an httpx.Client cost ~200ms per request because every
    # call used httpx.get/httpx.patch, which build a fresh client each time.
    fake, client_cls = http

    api_client.get_summary()
    api_client.get_transactions(category="Groceries")
    api_client.get_suggested_transfer_match(1)
    api_client.correct_transaction_category(1, category="Groceries")

    client_cls.assert_called_once()
    assert client_cls.call_args.kwargs["base_url"] == api_client.BASE_URL
    assert fake.get.call_count == 3
    assert fake.patch.call_count == 1


def test_requests_keep_the_same_paths_and_params(http):
    fake, _ = http

    api_client.get_summary(date_from=date(2026, 8, 1), date_to=date(2026, 8, 31))
    api_client.get_transactions(needs_review=True, transfer_group_id=7)
    api_client.get_suggested_transfer_match(42)
    api_client.confirm_transfer_with_id(5, 9)

    get_calls = [(c.args[0], c.kwargs.get("params")) for c in fake.get.call_args_list]
    assert get_calls == [
        ("/summary", {"date_from": "2026-08-01", "date_to": "2026-08-31"}),
        ("/transactions", {"needs_review": True, "transfer_group_id": 7}),
        ("/transactions/42/suggested-transfer-match", None),
    ]
    fake.patch.assert_called_once_with("/transactions/5", json={"confirm_transfer_with_id": 9})


def test_repeated_identical_reads_are_served_from_cache(http):
    # P2: Streamlit reruns the whole page on every widget click; an unchanged read shouldn't
    # go back to the API each time.
    fake, _ = http
    fake.get.return_value = _response([{"id": 1}])

    first = api_client.get_transactions(category="Groceries")
    second = api_client.get_transactions(category="Groceries")

    assert fake.get.call_count == 1
    assert first == second == [{"id": 1}]


def test_different_arguments_are_cached_separately(http):
    fake, _ = http

    api_client.get_transactions(category="Groceries")
    api_client.get_transactions(category="Transport")

    assert fake.get.call_count == 2


@pytest.mark.parametrize(
    "write",
    [
        lambda: api_client.correct_transaction_category(1, category="Groceries"),
        lambda: api_client.correct_transaction_is_refund(1, True),
        lambda: api_client.confirm_transfer_match(1),
        lambda: api_client.confirm_transfer_with_id(1, 2),
        lambda: api_client.reject_transfer_match(1),
    ],
    ids=["category", "is_refund", "confirm_match", "confirm_with_id", "reject_match"],
)
def test_every_write_invalidates_cached_reads(http, write):
    # Otherwise a correction wouldn't show up until the cache expired -- Category Drill-in and
    # Needs Review both rerun straight after a save, expecting fresh data.
    fake, _ = http

    api_client.get_summary()
    api_client.get_transactions(needs_review=True)
    api_client.get_suggested_transfer_match(3)
    write()
    api_client.get_summary()
    api_client.get_transactions(needs_review=True)
    api_client.get_suggested_transfer_match(3)

    assert fake.get.call_count == 6


def test_a_failed_write_still_invalidates_cached_reads(http):
    # The backend may have applied part of a request before failing; refetching is the safe side.
    fake, _ = http
    api_client.get_summary()
    fake.patch.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
        "boom", request=MagicMock(), response=MagicMock()
    )

    with pytest.raises(httpx.HTTPStatusError):
        api_client.reject_transfer_match(1)
    api_client.get_summary()

    assert fake.get.call_count == 2


def test_a_failed_read_is_not_cached(http):
    # An error shown on the page must not stick for the cache's lifetime once the API recovers.
    fake, _ = http
    failing = _response(None)
    failing.raise_for_status.side_effect = httpx.HTTPStatusError(
        "boom", request=MagicMock(), response=MagicMock()
    )
    fake.get.side_effect = [failing, _response({"total_income": 1.0})]

    with pytest.raises(httpx.HTTPStatusError):
        api_client.get_summary()
    assert api_client.get_summary() == {"total_income": 1.0}
    assert fake.get.call_count == 2
