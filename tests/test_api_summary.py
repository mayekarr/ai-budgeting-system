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
