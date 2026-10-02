from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.api as api_module
from backend.models import Account, Base, Transaction


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test_finance.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(bind=engine)
    monkeypatch.setattr(api_module, "engine", engine)
    monkeypatch.setattr(api_module, "SessionLocal", TestSessionLocal)
    Base.metadata.create_all(bind=engine)

    with TestSessionLocal() as seed:
        account = Account(name="CC", institution="NAB", owner="Rohan", account_type="Credit Card")
        seed.add(account)
        seed.commit()
        account_id = account.id

    return TestClient(api_module.app), TestSessionLocal, account_id


def _seed(SessionLocal, account_id, **overrides):
    defaults = dict(
        account_id=account_id,
        date=date(2026, 8, 1),
        amount=-10.0,
        raw_description="TEST TXN",
        category="Miscellaneous",
        subcategory=None,
        type="Expense",
        is_refund=False,
        transfer_group_id=None,
        superseded_by_id=None,
        source="bank_import",
        needs_review=False,
        confidence_score=1.0,
    )
    defaults.update(overrides)
    with SessionLocal() as session:
        tx = Transaction(**defaults)
        session.add(tx)
        session.commit()
        session.refresh(tx)
        return tx.id


def test_summary_totals_income_and_expense_excluding_transfers_and_superseded(client):
    api_client, SessionLocal, account_id = client
    _seed(SessionLocal, account_id, category="Income", subcategory="Salary", amount=5000.0, type="Income")
    _seed(SessionLocal, account_id, category="Groceries", amount=-100.0, type="Expense")
    _seed(SessionLocal, account_id, category="Transport", amount=-50.0, type="Expense")
    # Excluded: a Transfer between the user's own accounts.
    _seed(SessionLocal, account_id, category=None, amount=200.0, type="Transfer")
    # Excluded: a pending row superseded by its settled counterpart.
    settled_id = _seed(SessionLocal, account_id, category="Shopping", amount=-30.0, type="Expense")
    _seed(SessionLocal, account_id, category="Shopping", amount=-30.0, type="Expense", superseded_by_id=settled_id)

    body = api_client.get("/summary").json()

    assert body["total_income"] == 5000.0
    # 100 (Groceries) + 50 (Transport) + 30 (the one active Shopping row) = 180
    assert body["total_expense"] == 180.0
    assert body["net"] == 5000.0 - 180.0


def test_summary_nets_refund_credit_against_its_category_not_as_income(client):
    api_client, SessionLocal, account_id = client
    _seed(SessionLocal, account_id, category="Health & Medical", subcategory="Medical", amount=-200.0, type="Expense")
    # A genuine merchant refund: positive amount, is_refund=True, same category as the purchase.
    # Per the existing sign-based `type` assignment this lands as type="Income" — the netting logic
    # must not be fooled by that; it must key off `category`, not `type` (FR-9b).
    _seed(
        SessionLocal, account_id, category="Health & Medical", subcategory="Medical",
        amount=50.0, type="Income", is_refund=True,
    )

    body = api_client.get("/summary").json()

    assert body["total_income"] == 0.0  # the refund must NOT be counted as income
    assert body["total_expense"] == 150.0  # 200 - 50, netted within the category
    category_row = next(c for c in body["by_category"] if c["category"] == "Health & Medical")
    assert category_row["amount"] == 150.0


def test_summary_ato_tax_refund_counts_as_income_not_netted(client):
    api_client, SessionLocal, account_id = client
    _seed(SessionLocal, account_id, category="Groceries", amount=-100.0, type="Expense")
    _seed(
        SessionLocal, account_id, category="Income", subcategory="Tax Refund",
        amount=450.0, type="Income", is_refund=False,
    )

    body = api_client.get("/summary").json()

    assert body["total_income"] == 450.0
    assert body["total_expense"] == 100.0
    assert all(c["category"] != "Income" for c in body["by_category"])


def test_summary_includes_earnings_breakdown_by_subcategory(client):
    # Rohan's request: "there should also be a drill down for earnings" -- Overview's spend chart
    # deliberately excludes Income (it's a different grouping axis: every income row shares
    # category=Income, so subcategory -- Salary vs Dividends vs Tax Refund -- is the meaningful
    # breakdown, not category). This backs the new "Earnings by Source" chart.
    api_client, SessionLocal, account_id = client
    _seed(SessionLocal, account_id, category="Income", subcategory="Salary", amount=5000.0, type="Income")
    _seed(SessionLocal, account_id, category="Income", subcategory="Salary", amount=300.0, type="Income")
    _seed(SessionLocal, account_id, category="Income", subcategory="Dividends & Distributions", amount=200.0, type="Income")
    _seed(SessionLocal, account_id, category="Income", subcategory=None, amount=50.0, type="Income")
    _seed(SessionLocal, account_id, category="Groceries", amount=-100.0, type="Expense")
    # Excluded, same as the rest of the summary: a Transfer between the user's own accounts.
    _seed(SessionLocal, account_id, category=None, amount=500.0, type="Transfer")

    body = api_client.get("/summary").json()

    by_income = {row["category"]: row["amount"] for row in body["by_income_category"]}
    assert by_income == {"Salary": 5300.0, "Dividends & Distributions": 200.0, "Uncategorized": 50.0}
    # Sorted descending by amount, same convention as by_category.
    assert [row["category"] for row in body["by_income_category"]] == [
        "Salary", "Dividends & Distributions", "Uncategorized",
    ]
    # Expense/Transfer rows must not leak into the earnings breakdown.
    assert "Groceries" not in by_income


def test_summary_filters_by_date_range(client):
    api_client, SessionLocal, account_id = client
    _seed(SessionLocal, account_id, date=date(2026, 7, 15), category="Groceries", amount=-100.0)
    _seed(SessionLocal, account_id, date=date(2026, 8, 15), category="Groceries", amount=-40.0)

    body = api_client.get(
        "/summary", params={"date_from": "2026-08-01", "date_to": "2026-08-31"}
    ).json()

    assert body["total_expense"] == 40.0


def test_summary_by_category_sorted_by_spend_descending(client):
    api_client, SessionLocal, account_id = client
    _seed(SessionLocal, account_id, category="Groceries", amount=-40.0)
    _seed(SessionLocal, account_id, category="Transport", amount=-100.0)
    _seed(SessionLocal, account_id, category="Shopping", amount=-10.0)

    body = api_client.get("/summary").json()
    categories = [c["category"] for c in body["by_category"]]

    assert categories == ["Transport", "Groceries", "Shopping"]


def test_summary_filters_by_account_id(client):
    api_client, SessionLocal, account_id = client
    with SessionLocal() as seed:
        other_account = Account(name="JC", institution="NAB", owner="Rohan", account_type="Everyday")
        seed.add(other_account)
        seed.commit()
        other_account_id = other_account.id

    _seed(SessionLocal, account_id, category="Groceries", amount=-40.0)
    _seed(SessionLocal, other_account_id, category="Groceries", amount=-999.0)

    body = api_client.get("/summary", params={"account_id": account_id}).json()

    assert body["total_expense"] == 40.0


def test_transactions_drill_in_filters_by_category_and_date_range(client):
    # J3: Category Drill-in needs the clicked category's transactions within the active date range.
    api_client, SessionLocal, account_id = client
    _seed(SessionLocal, account_id, date=date(2026, 8, 5), category="Groceries", raw_description="IN RANGE")
    _seed(SessionLocal, account_id, date=date(2026, 7, 5), category="Groceries", raw_description="BEFORE RANGE")
    _seed(SessionLocal, account_id, date=date(2026, 8, 5), category="Transport", raw_description="WRONG CATEGORY")

    listed = api_client.get(
        "/transactions",
        params={"category": "Groceries", "date_from": "2026-08-01", "date_to": "2026-08-31"},
    ).json()

    assert len(listed) == 1
    assert listed[0]["raw_description"] == "IN RANGE"


def _tax_refund(SessionLocal, account_id, d, amount, **overrides):
    fields = dict(category="Income", subcategory="Tax Refund", type="Income", raw_description="ATO TAX REFUND")
    fields.update(overrides)
    return _seed(SessionLocal, account_id, date=d, amount=amount, **fields)


def _yearly(api_client, **params):
    return api_client.get(
        "/summary/by-year", params={"category": "Income", "subcategory": "Tax Refund", **params}
    )


def test_by_year_sums_tax_refunds_per_calendar_year_received(client):
    # J7. Real history (Source 2): refunds land Sep-Dec, after the 30 June FY end -- so the calendar
    # year received is also the FY the refund is for, and matches Rohan's own "Tax Refunds 2012" naming.
    api_client, SessionLocal, account_id = client
    _tax_refund(SessionLocal, account_id, date(2018, 10, 22), 2356.82)
    _tax_refund(SessionLocal, account_id, date(2018, 10, 25), 2689.32)
    _tax_refund(SessionLocal, account_id, date(2019, 9, 17), 2062.26)

    response = _yearly(api_client)

    assert response.status_code == 200
    assert response.json() == [
        {"year": 2018, "amount": pytest.approx(5046.14), "count": 2},
        {"year": 2019, "amount": pytest.approx(2062.26), "count": 1},
    ]


def test_by_year_shows_gap_years_as_zero(client):
    # A year with no refund is part of the year-on-year story, not a missing bar.
    api_client, SessionLocal, account_id = client
    _tax_refund(SessionLocal, account_id, date(2019, 9, 17), 100.0)
    _tax_refund(SessionLocal, account_id, date(2021, 9, 30), 300.0)

    years = _yearly(api_client).json()

    assert [(y["year"], y["amount"], y["count"]) for y in years] == [
        (2019, 100.0, 1), (2020, 0.0, 0), (2021, 300.0, 1),
    ]


def test_by_year_only_counts_the_requested_subcategory(client):
    api_client, SessionLocal, account_id = client
    _tax_refund(SessionLocal, account_id, date(2020, 12, 8), 865.67)
    _seed(SessionLocal, account_id, date=date(2020, 12, 1), amount=5000.0, category="Income",
          subcategory="Salary", type="Income")
    _seed(SessionLocal, account_id, date=date(2020, 11, 1), amount=-899.75, category="Government & Tax",
          subcategory="Tax Paid")

    assert _yearly(api_client).json() == [{"year": 2020, "amount": pytest.approx(865.67), "count": 1}]


def test_by_year_excludes_transfers_and_superseded_rows(client):
    api_client, SessionLocal, account_id = client
    kept = _tax_refund(SessionLocal, account_id, date(2021, 9, 30), 9402.36)
    _tax_refund(SessionLocal, account_id, date(2021, 9, 30), 9402.36, type="Transfer")
    _tax_refund(SessionLocal, account_id, date(2021, 9, 29), 9402.36, superseded_by_id=kept)

    assert _yearly(api_client).json() == [{"year": 2021, "amount": pytest.approx(9402.36), "count": 1}]


def test_by_year_with_no_matching_rows_is_empty(client):
    api_client, _, _ = client
    assert _yearly(api_client).json() == []


def test_by_year_category_only_groups_the_whole_category(client):
    api_client, SessionLocal, account_id = client
    _tax_refund(SessionLocal, account_id, date(2020, 12, 8), 865.67)
    _seed(SessionLocal, account_id, date=date(2020, 12, 1), amount=5000.0, category="Income",
          subcategory="Salary", type="Income")

    response = api_client.get("/summary/by-year", params={"category": "Income"})

    assert response.json() == [{"year": 2020, "amount": pytest.approx(5865.67), "count": 2}]


def test_by_year_requires_a_category(client):
    api_client, _, _ = client
    assert api_client.get("/summary/by-year").status_code == 422
