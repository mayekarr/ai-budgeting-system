from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

_DASHBOARD_PATH = Path(__file__).resolve().parent.parent / "frontend" / "dashboard.py"


def _fake_transactions(*args, **kwargs):
    return [
        {
            "id": 1, "date": "2026-08-05", "raw_description": "WOOLWORTHS/MAIN ST", "amount": -40.0,
            "category": "Groceries", "subcategory": None, "type": "Expense", "is_refund": False,
            "transfer_group_id": None, "needs_review": False,
        },
        {
            "id": 2, "date": "2026-08-06", "raw_description": "MYKI PAYMENTS", "amount": -10.0,
            "category": "Transport", "subcategory": "Public Transport", "type": "Expense",
            "is_refund": False, "transfer_group_id": None, "needs_review": False,
        },
    ]


def _open_drill_in() -> AppTest:
    at = AppTest.from_file(str(_DASHBOARD_PATH), default_timeout=15)
    at.run()
    at.switch_page("pages/2_Category_Drill_in.py")
    return at


def test_correction_control_lists_currently_shown_transactions():
    with patch("frontend.api_client.get_transactions", side_effect=_fake_transactions):
        at = _open_drill_in()
        at.run()

    assert not at.exception
    options = at.selectbox(key="drill_in_correction_tx_select").options
    assert len(options) == 2


def test_correction_subcategory_options_scoped_to_selected_category():
    with patch("frontend.api_client.get_transactions", side_effect=_fake_transactions):
        at = _open_drill_in()
        at.run()
        at.selectbox(key="drill_in_correction_category_select").select("Cafes & Restaurants").run()

    assert not at.exception
    sub_options = at.selectbox(key="drill_in_correction_subcategory_select").options
    assert sub_options == ["", "Restaurants & Takeaway", "Cafes & Coffee"]


def test_saving_a_correction_calls_the_api_with_the_selected_transaction_and_category():
    with patch("frontend.api_client.get_transactions", side_effect=_fake_transactions):
        at = _open_drill_in()
        at.run()

        with patch("frontend.api_client.correct_transaction_category") as mock_correct:
            at.selectbox(key="drill_in_correction_tx_select").select(2).run()
            at.selectbox(key="drill_in_correction_category_select").select("Cafes & Restaurants").run()
            at.selectbox(key="drill_in_correction_subcategory_select").select("Cafes & Coffee").run()
            at.button(key="drill_in_save_correction_button").click().run()

    assert not at.exception
    mock_correct.assert_called_once_with(2, category="Cafes & Restaurants", subcategory="Cafes & Coffee")


def test_saving_a_correction_with_no_subcategory_passes_none():
    with patch("frontend.api_client.get_transactions", side_effect=_fake_transactions):
        at = _open_drill_in()
        at.run()

        with patch("frontend.api_client.correct_transaction_category") as mock_correct:
            at.selectbox(key="drill_in_correction_tx_select").select(1).run()
            at.selectbox(key="drill_in_correction_category_select").select("Groceries").run()
            at.button(key="drill_in_save_correction_button").click().run()

    assert not at.exception
    mock_correct.assert_called_once_with(1, category="Groceries", subcategory=None)


def test_saving_a_correction_triggers_a_refetch_so_the_table_reflects_it():
    # A run always fetches once at the top of the script before the button handler further down
    # even sees the click — so that first fetch is inherently stale (it ran before the correction
    # was applied). Without an explicit rerun after a successful save, that stale fetch is all a
    # click produces, and the visible table stays wrong until some later, unrelated interaction.
    # The fix reruns after a successful save, producing a second, fresh fetch in the same action —
    # i.e. clicking Save should cost *two* fetches (stale, then fresh), not the normal one.
    with patch("frontend.api_client.get_transactions", side_effect=_fake_transactions) as mock_get:
        at = _open_drill_in()
        at.run()
        at.selectbox(key="drill_in_correction_tx_select").select(1).run()
        count_before_save = mock_get.call_count

        with patch("frontend.api_client.correct_transaction_category"):
            at.button(key="drill_in_save_correction_button").click().run()

    assert not at.exception
    assert mock_get.call_count == count_before_save + 2


def test_saving_a_correction_shows_a_success_message():
    with patch("frontend.api_client.get_transactions", side_effect=_fake_transactions):
        at = _open_drill_in()
        at.run()

        with patch("frontend.api_client.correct_transaction_category"):
            at.selectbox(key="drill_in_correction_tx_select").select(1).run()
            at.button(key="drill_in_save_correction_button").click().run()

    assert not at.exception
    assert any("updated" in s.value.lower() for s in at.success)


def test_saving_a_correction_shows_an_error_on_api_failure():
    with patch("frontend.api_client.get_transactions", side_effect=_fake_transactions):
        at = _open_drill_in()
        at.run()

        with patch("frontend.api_client.correct_transaction_category", side_effect=RuntimeError("boom")):
            at.selectbox(key="drill_in_correction_tx_select").select(1).run()
            at.button(key="drill_in_save_correction_button").click().run()

    assert not at.exception
    assert any("boom" in e.value for e in at.error)


def test_no_correction_control_when_no_transactions_in_view():
    with patch("frontend.api_client.get_transactions", side_effect=lambda *a, **k: []):
        at = _open_drill_in()
        at.run()

    assert not at.exception
    assert len(at.selectbox) == 1  # only the category filter selectbox, no correction control
