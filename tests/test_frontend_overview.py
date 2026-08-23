from __future__ import annotations

from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from frontend.categories import ALL_CATEGORIES


def _fake_summary(*args, **kwargs):
    return {
        "date_from": None,
        "date_to": None,
        "total_income": 5000.0,
        "total_expense": 180.0,
        "net": 4820.0,
        "by_category": [
            {"category": "Transport", "amount": 100.0},
            {"category": "Groceries", "amount": 80.0},
        ],
    }


def test_overview_renders_kpis_from_summary():
    with patch("frontend.api_client.get_summary", side_effect=_fake_summary):
        at = AppTest.from_file("frontend/pages/1_Overview.py", default_timeout=15)
        at.run()

    assert at.metric[0].value == "$5,000.00"
    assert at.metric[1].value == "$180.00"
    assert at.metric[2].value == "$4,820.00"


def test_overview_passes_resolved_date_range_to_summary():
    with patch("frontend.api_client.get_summary", side_effect=_fake_summary) as mock_get:
        at = AppTest.from_file("frontend/pages/1_Overview.py", default_timeout=15)
        at.run()

    _, kwargs = mock_get.call_args
    assert kwargs["date_from"] is not None
    assert kwargs["date_to"] is not None


def test_selecting_category_stores_it_for_drill_in():
    with patch("frontend.api_client.get_summary", side_effect=_fake_summary):
        at = AppTest.from_file("frontend/pages/1_Overview.py", default_timeout=15)
        at.run()
        at.selectbox(key="overview_selected_category").select("Groceries").run()

    assert at.session_state["drill_in_category"] == "Groceries"


def test_category_dropdown_offers_all_categories_option():
    with patch("frontend.api_client.get_summary", side_effect=_fake_summary):
        at = AppTest.from_file("frontend/pages/1_Overview.py", default_timeout=15)
        at.run()

    options = at.selectbox(key="overview_selected_category").options
    assert options == [ALL_CATEGORIES, "Transport", "Groceries"]


def test_selecting_all_categories_stores_the_sentinel_for_drill_in():
    with patch("frontend.api_client.get_summary", side_effect=_fake_summary):
        at = AppTest.from_file("frontend/pages/1_Overview.py", default_timeout=15)
        at.run()
        at.selectbox(key="overview_selected_category").select(ALL_CATEGORIES).run()

    assert at.session_state["drill_in_category"] == ALL_CATEGORIES


def test_overview_shows_info_when_no_transactions_in_range():
    def _empty_summary(*args, **kwargs):
        return {
            "date_from": None, "date_to": None,
            "total_income": 0.0, "total_expense": 0.0, "net": 0.0,
            "by_category": [],
        }

    with patch("frontend.api_client.get_summary", side_effect=_empty_summary):
        at = AppTest.from_file("frontend/pages/1_Overview.py", default_timeout=15)
        at.run()

    assert not at.exception
    assert any("No transactions" in i.value for i in at.info)
