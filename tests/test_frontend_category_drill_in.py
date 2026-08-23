from __future__ import annotations

from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from frontend.categories import ALL_CATEGORIES


def _fake_all_transactions(*args, **kwargs):
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
        {
            "id": 3, "date": "2026-08-08", "raw_description": "SALARY PAYMENT ACME CO", "amount": 5000.0,
            "category": "Income", "subcategory": "Salary", "type": "Income", "is_refund": False,
            "transfer_group_id": None, "needs_review": False,
        },
    ]


def test_drill_in_fetches_the_date_range_unfiltered_by_category():
    # Fetched once, unfiltered — the category dropdown's own options (and any client-side
    # filtering) are derived from this single result set, not a second server round trip.
    with patch("frontend.api_client.get_transactions", side_effect=_fake_all_transactions) as mock_get:
        at = AppTest.from_file("frontend/pages/2_Category_Drill_in.py", default_timeout=15)
        at.run()

    _, kwargs = mock_get.call_args
    assert kwargs["category"] is None
    assert mock_get.call_count == 1


def test_drill_in_category_options_include_income():
    # GET /summary's by_category excludes Income (it's not a spend category) — Drill-in must not
    # inherit that exclusion, since browsing Income transactions is still a legitimate use of this
    # page even though Overview's spend chart doesn't surface it.
    with patch("frontend.api_client.get_transactions", side_effect=_fake_all_transactions):
        at = AppTest.from_file("frontend/pages/2_Category_Drill_in.py", default_timeout=15)
        at.run()

    options = at.selectbox(key="drill_in_category_select").options
    assert options == [ALL_CATEGORIES, "Groceries", "Income", "Transport"]


def test_drill_in_defaults_to_all_categories_when_arriving_directly():
    with patch("frontend.api_client.get_transactions", side_effect=_fake_all_transactions):
        at = AppTest.from_file("frontend/pages/2_Category_Drill_in.py", default_timeout=15)
        at.run()

    assert at.selectbox(key="drill_in_category_select").value == ALL_CATEGORIES
    assert len(at.dataframe[0].value) == 3


def test_drill_in_defaults_to_category_from_session_state():
    with patch("frontend.api_client.get_transactions", side_effect=_fake_all_transactions):
        at = AppTest.from_file("frontend/pages/2_Category_Drill_in.py", default_timeout=15)
        at.session_state["drill_in_category"] = "Groceries"
        at.run()

    assert at.selectbox(key="drill_in_category_select").value == "Groceries"
    shown = at.dataframe[0].value
    assert len(shown) == 1
    assert shown.iloc[0]["raw_description"] == "WOOLWORTHS/MAIN ST"


def test_selecting_a_category_filters_the_table_client_side():
    with patch("frontend.api_client.get_transactions", side_effect=_fake_all_transactions):
        at = AppTest.from_file("frontend/pages/2_Category_Drill_in.py", default_timeout=15)
        at.run()
        at.selectbox(key="drill_in_category_select").select("Transport").run()

    shown = at.dataframe[0].value
    assert len(shown) == 1
    assert shown.iloc[0]["raw_description"] == "MYKI PAYMENTS"


def test_selecting_all_categories_shows_everything():
    with patch("frontend.api_client.get_transactions", side_effect=_fake_all_transactions):
        at = AppTest.from_file("frontend/pages/2_Category_Drill_in.py", default_timeout=15)
        at.session_state["drill_in_category"] = "Groceries"
        at.run()
        at.selectbox(key="drill_in_category_select").select(ALL_CATEGORIES).run()

    assert len(at.dataframe[0].value) == 3


def test_drill_in_shows_info_when_no_transactions_in_range():
    with patch("frontend.api_client.get_transactions", side_effect=lambda *a, **k: []):
        at = AppTest.from_file("frontend/pages/2_Category_Drill_in.py", default_timeout=15)
        at.run()

    assert not at.exception
    assert at.selectbox(key="drill_in_category_select").options == [ALL_CATEGORIES]
    assert any("No transactions" in i.value for i in at.info)
