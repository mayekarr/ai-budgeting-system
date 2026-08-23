from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from frontend.categories import ALL_CATEGORIES

_DASHBOARD_PATH = Path(__file__).resolve().parent.parent / "frontend" / "dashboard.py"


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


def _open_drill_in() -> AppTest:
    # Loaded through the real multipage entrypoint (dashboard.py) + switch_page, matching how a
    # user actually reaches this page (and how tests/test_frontend_overview.py now loads Overview),
    # rather than AppTest.from_file("frontend/pages/2_Category_Drill_in.py") in isolation.
    #
    # Path is absolute (see tests/test_frontend_overview.py for why): AppTest's relative-path
    # resolution differs across streamlit versions, so an absolute path sidesteps that entirely.
    at = AppTest.from_file(str(_DASHBOARD_PATH), default_timeout=15)
    at.run()
    at.switch_page("pages/2_Category_Drill_in.py")
    return at


def test_drill_in_fetches_the_date_range_unfiltered_by_category():
    # Fetched once, unfiltered — the category dropdown's own options (and any client-side
    # filtering) are derived from this single result set, not a second server round trip.
    with patch("frontend.api_client.get_transactions", side_effect=_fake_all_transactions) as mock_get:
        at = _open_drill_in()
        at.run()

    assert not at.exception
    _, kwargs = mock_get.call_args
    assert kwargs["category"] is None
    assert mock_get.call_count == 1


def test_drill_in_category_options_include_income():
    # GET /summary's by_category excludes Income (it's not a spend category) — Drill-in must not
    # inherit that exclusion, since browsing Income transactions is still a legitimate use of this
    # page even though Overview's spend chart doesn't surface it.
    with patch("frontend.api_client.get_transactions", side_effect=_fake_all_transactions):
        at = _open_drill_in()
        at.run()

    assert not at.exception
    options = at.selectbox(key="drill_in_category_select").options
    assert options == [ALL_CATEGORIES, "Groceries", "Income", "Transport"]


def test_drill_in_defaults_to_all_categories_when_arriving_directly():
    with patch("frontend.api_client.get_transactions", side_effect=_fake_all_transactions):
        at = _open_drill_in()
        at.run()

    assert not at.exception
    assert at.selectbox(key="drill_in_category_select").value == ALL_CATEGORIES
    assert len(at.dataframe[0].value) == 3


def test_drill_in_defaults_to_category_from_session_state():
    with patch("frontend.api_client.get_transactions", side_effect=_fake_all_transactions):
        at = _open_drill_in()
        at.session_state["drill_in_category"] = "Groceries"
        at.run()

    assert not at.exception
    assert at.selectbox(key="drill_in_category_select").value == "Groceries"
    shown = at.dataframe[0].value
    assert len(shown) == 1
    assert shown.iloc[0]["raw_description"] == "WOOLWORTHS/MAIN ST"


def test_selecting_a_category_filters_the_table_client_side():
    with patch("frontend.api_client.get_transactions", side_effect=_fake_all_transactions):
        at = _open_drill_in()
        at.run()
        at.selectbox(key="drill_in_category_select").select("Transport").run()

    assert not at.exception
    shown = at.dataframe[0].value
    assert len(shown) == 1
    assert shown.iloc[0]["raw_description"] == "MYKI PAYMENTS"


def test_selecting_all_categories_shows_everything():
    with patch("frontend.api_client.get_transactions", side_effect=_fake_all_transactions):
        at = _open_drill_in()
        at.session_state["drill_in_category"] = "Groceries"
        at.run()
        at.selectbox(key="drill_in_category_select").select(ALL_CATEGORIES).run()

    assert not at.exception
    assert len(at.dataframe[0].value) == 3


def test_returning_from_overview_with_a_new_category_overrides_the_stale_selection():
    # Streamlit persists a widget's own session_state entry (keyed by `key=`) across reruns and
    # ignores `index=` once that entry exists — so a second Overview -> Drill-in handoff with a
    # different category must not leave the first visit's selection stuck.
    with patch("frontend.api_client.get_transactions", side_effect=_fake_all_transactions):
        at = _open_drill_in()
        at.session_state["drill_in_category"] = "Groceries"
        at.run()
        assert at.selectbox(key="drill_in_category_select").value == "Groceries"

        at.session_state["drill_in_category"] = "Transport"
        at.run()

    assert not at.exception
    assert at.selectbox(key="drill_in_category_select").value == "Transport"
    shown = at.dataframe[0].value
    assert len(shown) == 1
    assert shown.iloc[0]["raw_description"] == "MYKI PAYMENTS"


def test_drill_in_excludes_transfer_typed_rows():
    # FR-9c/FR-13: Transfer rows are structurally excluded from category breakdowns, and FR-14's
    # drill-in is meant to show that same breakdown's underlying transactions — so a Transfer-typed
    # row must not appear here even though transfer detection never clears its pre-transfer
    # category (e.g. "Groceries"), and must not count toward that category's option/filter either.
    def fake_txns(*a, **k):
        return _fake_all_transactions() + [
            {
                "id": 4, "date": "2026-08-07", "raw_description": "CREDIT CARD PAYMENT", "amount": -200.0,
                "category": "Groceries", "subcategory": None, "type": "Transfer", "is_refund": False,
                "transfer_group_id": 1, "needs_review": False,
            },
        ]

    with patch("frontend.api_client.get_transactions", side_effect=fake_txns):
        at = _open_drill_in()
        at.session_state["drill_in_category"] = "Groceries"
        at.run()

    assert not at.exception
    shown = at.dataframe[0].value
    assert len(shown) == 1
    assert shown.iloc[0]["raw_description"] == "WOOLWORTHS/MAIN ST"


def test_drill_in_excludes_superseded_rows():
    # Matches GET /summary's own exclusion (superseded_by_id IS NOT NULL) — a pending row that's
    # since been resolved by its settled counterpart must not appear as a second, duplicate-looking
    # transaction in the list.
    def fake_txns(*a, **k):
        return [
            {
                "id": 1, "date": "2026-08-05", "raw_description": "PURCHASE AUTHORISATION", "amount": -40.0,
                "category": "Groceries", "subcategory": None, "type": "Expense", "is_refund": False,
                "transfer_group_id": None, "needs_review": False, "superseded_by_id": 2,
            },
            {
                "id": 2, "date": "2026-08-06", "raw_description": "WOOLWORTHS/MAIN ST", "amount": -40.0,
                "category": "Groceries", "subcategory": None, "type": "Expense", "is_refund": False,
                "transfer_group_id": None, "needs_review": False, "superseded_by_id": None,
            },
        ]

    with patch("frontend.api_client.get_transactions", side_effect=fake_txns):
        at = _open_drill_in()
        at.session_state["drill_in_category"] = "Groceries"
        at.run()

    assert not at.exception
    shown = at.dataframe[0].value
    assert len(shown) == 1
    assert shown.iloc[0]["raw_description"] == "WOOLWORTHS/MAIN ST"


def test_drill_in_shows_info_when_no_transactions_in_range():
    with patch("frontend.api_client.get_transactions", side_effect=lambda *a, **k: []):
        at = _open_drill_in()
        at.run()

    assert not at.exception
    assert at.selectbox(key="drill_in_category_select").options == [ALL_CATEGORIES]
    assert any("No transactions" in i.value for i in at.info)
