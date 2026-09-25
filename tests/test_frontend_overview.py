from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from frontend.categories import ALL_CATEGORIES

_DASHBOARD_PATH = Path(__file__).resolve().parent.parent / "frontend" / "dashboard.py"


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
        "by_income_category": [
            {"category": "Salary", "amount": 5000.0},
        ],
    }


def _open_overview() -> AppTest:
    # Loaded through the real multipage entrypoint (dashboard.py) + switch_page, not
    # AppTest.from_file("frontend/pages/1_Overview.py") directly: the latter runs the page with no
    # page registry, so st.page_link's target-page lookup throws (KeyError: 'url_pathname') even
    # though the real app never hits that — a false positive that earlier tests here didn't catch
    # since none asserted `at.exception`. This mirrors how a user actually reaches the page.
    #
    # Path is absolute, not the relative "frontend/dashboard.py" this used to pass: AppTest's
    # relative-path resolution differs across streamlit versions (some try cwd first, some only
    # ever resolve against the calling test file's own directory) — an absolute path sidesteps
    # that ambiguity entirely instead of depending on which behaviour happens to be installed.
    at = AppTest.from_file(str(_DASHBOARD_PATH), default_timeout=15)
    at.run()
    at.switch_page("pages/1_Overview.py")
    return at


def test_overview_renders_kpis_from_summary():
    with patch("frontend.api_client.get_summary", side_effect=_fake_summary):
        at = _open_overview()
        at.run()

    assert not at.exception
    assert at.metric[0].value == "$5,000.00"
    assert at.metric[1].value == "$180.00"
    assert at.metric[2].value == "$4,820.00"


def test_overview_passes_resolved_date_range_to_summary():
    with patch("frontend.api_client.get_summary", side_effect=_fake_summary) as mock_get:
        at = _open_overview()
        at.run()

    assert not at.exception
    _, kwargs = mock_get.call_args
    assert kwargs["date_from"] is not None
    assert kwargs["date_to"] is not None


def test_selecting_category_stores_it_for_drill_in():
    with patch("frontend.api_client.get_summary", side_effect=_fake_summary):
        at = _open_overview()
        at.run()
        at.selectbox(key="overview_selected_category").select("Groceries").run()

    assert not at.exception
    assert at.session_state["drill_in_category"] == "Groceries"


def test_category_dropdown_offers_all_categories_option():
    with patch("frontend.api_client.get_summary", side_effect=_fake_summary):
        at = _open_overview()
        at.run()

    assert not at.exception
    options = at.selectbox(key="overview_selected_category").options
    # "Income" is appended after the spend categories -- there's a drill down for earnings too
    # (Rohan's request), reusing this same selector/link rather than a second, competing one.
    assert options == [ALL_CATEGORIES, "Transport", "Groceries", "Income"]


def test_selecting_income_stores_it_for_drill_in():
    with patch("frontend.api_client.get_summary", side_effect=_fake_summary):
        at = _open_overview()
        at.run()
        at.selectbox(key="overview_selected_category").select("Income").run()

    assert not at.exception
    assert at.session_state["drill_in_category"] == "Income"


def test_overview_shows_earnings_by_source_chart():
    with patch("frontend.api_client.get_summary", side_effect=_fake_summary):
        at = _open_overview()
        at.run()

    assert not at.exception
    assert any("Earnings by Source" in h.value for h in at.subheader)


def test_overview_hides_earnings_chart_when_no_income_in_range():
    def _no_income_summary(*args, **kwargs):
        return {
            "date_from": None, "date_to": None,
            "total_income": 0.0, "total_expense": 80.0, "net": -80.0,
            "by_category": [{"category": "Groceries", "amount": 80.0}],
            "by_income_category": [],
        }

    with patch("frontend.api_client.get_summary", side_effect=_no_income_summary):
        at = _open_overview()
        at.run()

    assert not at.exception
    assert not any("Earnings by Source" in h.value for h in at.subheader)
    # Income must still be offered as a drill-in target even with $0 in range -- Drill-in already
    # handles an empty selection gracefully ("No transactions found"), same as any other category.
    options = at.selectbox(key="overview_selected_category").options
    assert "Income" in options


def test_selecting_all_categories_stores_the_sentinel_for_drill_in():
    with patch("frontend.api_client.get_summary", side_effect=_fake_summary):
        at = _open_overview()
        at.run()
        at.selectbox(key="overview_selected_category").select(ALL_CATEGORIES).run()

    assert not at.exception
    assert at.session_state["drill_in_category"] == ALL_CATEGORIES


def test_overview_shows_info_when_no_transactions_in_range():
    def _empty_summary(*args, **kwargs):
        return {
            "date_from": None, "date_to": None,
            "total_income": 0.0, "total_expense": 0.0, "net": 0.0,
            "by_category": [],
            "by_income_category": [],
        }

    with patch("frontend.api_client.get_summary", side_effect=_empty_summary):
        at = _open_overview()
        at.run()

    assert not at.exception
    assert any("No transactions" in i.value for i in at.info)
