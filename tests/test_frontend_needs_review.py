from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

_DASHBOARD_PATH = Path(__file__).resolve().parent.parent / "frontend" / "dashboard.py"


def _tx(tx_id, reason, **overrides):
    base = {
        "id": tx_id, "date": "2026-08-05", "raw_description": f"Row {tx_id}", "amount": -40.0,
        "category": "Miscellaneous", "subcategory": None, "type": "Expense", "is_refund": False,
        "transfer_group_id": None, "needs_review": True, "needs_review_reason": reason,
    }
    base.update(overrides)
    return base


def _open_needs_review() -> AppTest:
    at = AppTest.from_file(str(_DASHBOARD_PATH), default_timeout=15)
    at.run()
    at.switch_page("pages/3_Needs_Review.py")
    return at


def test_empty_queue_shows_info_message():
    with patch("frontend.api_client.get_transactions", return_value=[]):
        at = _open_needs_review()
        at.run()

    assert not at.exception
    assert any("nothing needs review" in i.value.lower() for i in at.info)


def test_reason_filter_narrows_the_shown_items():
    items = [
        _tx(1, "low_confidence_category"),
        _tx(2, "refund_ambiguity"),
    ]
    with patch("frontend.api_client.get_transactions", return_value=items):
        at = _open_needs_review()
        at.run()
        at.selectbox(key="needs_review_reason_select").select("Refund ambiguity").run()

    assert not at.exception
    assert any("1 item" in c.value for c in at.caption)


def test_refund_ambiguity_yes_button_calls_is_refund_true():
    items = [_tx(1, "refund_ambiguity")]
    with patch("frontend.api_client.get_transactions", return_value=items):
        at = _open_needs_review()
        at.run()

        with patch("frontend.api_client.correct_transaction_is_refund") as mock_call:
            at.button(key="refund_yes_1").click().run()

    assert not at.exception
    mock_call.assert_called_once_with(1, True)


def test_refund_ambiguity_no_button_calls_is_refund_false():
    items = [_tx(1, "refund_ambiguity")]
    with patch("frontend.api_client.get_transactions", return_value=items):
        at = _open_needs_review()
        at.run()

        with patch("frontend.api_client.correct_transaction_is_refund") as mock_call:
            at.button(key="refund_no_1").click().run()

    assert not at.exception
    mock_call.assert_called_once_with(1, False)


def test_transfer_match_already_linked_shows_confirm_and_reject():
    items = [_tx(1, "transfer_match", transfer_group_id=7)]
    with patch("frontend.api_client.get_transactions", return_value=items):
        at = _open_needs_review()
        at.run()

    assert not at.exception
    assert at.button(key="confirm_linked_1") is not None
    assert at.button(key="reject_linked_1") is not None


def test_transfer_match_confirm_linked_calls_confirm_transfer_match():
    items = [_tx(1, "transfer_match", transfer_group_id=7)]
    with patch("frontend.api_client.get_transactions", return_value=items):
        at = _open_needs_review()
        at.run()

        with patch("frontend.api_client.confirm_transfer_match") as mock_call:
            at.button(key="confirm_linked_1").click().run()

    assert not at.exception
    mock_call.assert_called_once_with(1)


def test_transfer_match_reject_linked_calls_reject_transfer_match():
    items = [_tx(1, "transfer_match", transfer_group_id=7)]
    with patch("frontend.api_client.get_transactions", return_value=items):
        at = _open_needs_review()
        at.run()

        with patch("frontend.api_client.reject_transfer_match") as mock_call:
            at.button(key="reject_linked_1").click().run()

    assert not at.exception
    mock_call.assert_called_once_with(1)


def test_transfer_match_unlinked_shows_suggestion_and_confirm_calls_confirm_with_id():
    items = [_tx(1, "transfer_match", transfer_group_id=None)]
    suggestion = {
        "id": 42, "date": "2026-08-07", "raw_description": "Suggested counterpart", "amount": 40.0,
        "category": None, "subcategory": None, "type": "Income", "is_refund": False,
        "transfer_group_id": None, "needs_review": True, "needs_review_reason": "transfer_match",
    }
    with patch("frontend.api_client.get_transactions", return_value=items):
        with patch("frontend.api_client.get_suggested_transfer_match", return_value=suggestion):
            at = _open_needs_review()
            at.run()

            with patch("frontend.api_client.confirm_transfer_with_id") as mock_call:
                at.button(key="confirm_suggested_1").click().run()

    assert not at.exception
    mock_call.assert_called_once_with(1, 42)


def test_transfer_match_unlinked_no_suggestion_shows_dismiss():
    items = [_tx(1, "transfer_match", transfer_group_id=None)]
    with patch("frontend.api_client.get_transactions", return_value=items):
        with patch("frontend.api_client.get_suggested_transfer_match", return_value=None):
            at = _open_needs_review()
            at.run()

            with patch("frontend.api_client.reject_transfer_match") as mock_call:
                at.button(key="dismiss_1").click().run()

    assert not at.exception
    mock_call.assert_called_once_with(1)


def test_low_confidence_category_save_calls_correct_transaction_category():
    items = [_tx(1, "low_confidence_category", category="Groceries")]
    with patch("frontend.api_client.get_transactions", return_value=items):
        at = _open_needs_review()
        at.run()

        with patch("frontend.api_client.correct_transaction_category") as mock_call:
            at.selectbox(key="needs_review_category_1").select("Transport").run()
            at.button(key="save_category_1").click().run()

    assert not at.exception
    mock_call.assert_called_once_with(1, category="Transport", subcategory=None)


def test_unrecognised_account_shows_visibility_only_message():
    items = [_tx(1, "unrecognised_account")]
    with patch("frontend.api_client.get_transactions", return_value=items):
        at = _open_needs_review()
        at.run()

    assert not at.exception
    assert any("visibility only" in c.value.lower() for c in at.caption)
