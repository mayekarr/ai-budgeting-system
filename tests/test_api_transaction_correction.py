from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.api as api_module
from backend.models import Account, Base, CategorisationRule, Transaction


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
        raw_description="MISCLASSIFIED MERCHANT 123",
        category="Miscellaneous",
        subcategory=None,
        type="Expense",
        is_refund=False,
        transfer_group_id=None,
        superseded_by_id=None,
        source="bank_import",
        needs_review=True,
        confidence_score=0.4,
    )
    defaults.update(overrides)
    with SessionLocal() as session:
        tx = Transaction(**defaults)
        session.add(tx)
        session.commit()
        session.refresh(tx)
        return tx.id


def test_patch_corrects_category_and_subcategory(client):
    api_client, SessionLocal, account_id = client
    tx_id = _seed(SessionLocal, account_id)

    response = api_client.patch(
        f"/transactions/{tx_id}", json={"category": "Cafes & Restaurants", "subcategory": "Cafes & Coffee"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "Cafes & Restaurants"
    assert body["subcategory"] == "Cafes & Coffee"


def test_patch_clears_needs_review_and_sets_full_confidence(client):
    # A manual correction resolves the uncertainty FR-10's flag exists for.
    api_client, SessionLocal, account_id = client
    tx_id = _seed(SessionLocal, account_id, needs_review=True, confidence_score=0.4)

    body = api_client.patch(f"/transactions/{tx_id}", json={"category": "Groceries"}).json()

    assert body["needs_review"] is False
    assert body["confidence_score"] == 1.0


def test_patch_without_subcategory_clears_it(client):
    api_client, SessionLocal, account_id = client
    tx_id = _seed(SessionLocal, account_id, category="Groceries", subcategory=None)

    body = api_client.patch(f"/transactions/{tx_id}", json={"category": "Transport"}).json()

    assert body["category"] == "Transport"
    assert body["subcategory"] is None


def test_patch_writes_back_a_user_correction_rule_for_future_matches(client):
    # FR-9: closes the "learn from corrections" loop the same way an LLM promotion does.
    api_client, SessionLocal, account_id = client
    tx_id = _seed(SessionLocal, account_id, raw_description="ACME COFFEE ROASTERS 042")

    api_client.patch(
        f"/transactions/{tx_id}", json={"category": "Cafes & Restaurants", "subcategory": "Cafes & Coffee"}
    )

    with SessionLocal() as session:
        rules = session.query(CategorisationRule).filter(CategorisationRule.source == "user_correction").all()
    assert len(rules) == 1
    rule = rules[0]
    assert rule.pattern == "ACME COFFEE ROASTERS 042"
    assert rule.match_type == "exact"
    assert rule.category == "Cafes & Restaurants"
    assert rule.subcategory == "Cafes & Coffee"
    assert rule.is_active is True


def test_patch_updates_existing_user_correction_rule_instead_of_duplicating(client):
    api_client, SessionLocal, account_id = client
    tx_id_1 = _seed(SessionLocal, account_id, raw_description="ACME COFFEE ROASTERS 042")
    tx_id_2 = _seed(SessionLocal, account_id, raw_description="ACME COFFEE ROASTERS 042")

    api_client.patch(f"/transactions/{tx_id_1}", json={"category": "Cafes & Restaurants"})
    api_client.patch(f"/transactions/{tx_id_2}", json={"category": "Shopping", "subcategory": "Homeware"})

    with SessionLocal() as session:
        rules = session.query(CategorisationRule).filter(CategorisationRule.source == "user_correction").all()
    assert len(rules) == 1
    assert rules[0].category == "Shopping"
    assert rules[0].subcategory == "Homeware"


def test_patch_user_correction_rule_outranks_a_seeded_rule_on_next_match(client):
    api_client, SessionLocal, account_id = client
    with SessionLocal() as session:
        session.add(
            CategorisationRule(
                pattern="ACME COFFEE ROASTERS 042", match_type="exact",
                category="Miscellaneous", subcategory=None, priority=1, source="seeded", is_active=True,
            )
        )
        session.commit()
    tx_id = _seed(SessionLocal, account_id, raw_description="ACME COFFEE ROASTERS 042")

    api_client.patch(
        f"/transactions/{tx_id}", json={"category": "Cafes & Restaurants", "subcategory": "Cafes & Coffee"}
    )

    from categorisation.rules import match_rule
    with SessionLocal() as session:
        result = match_rule(session, "ACME COFFEE ROASTERS 042")
    assert result.category == "Cafes & Restaurants"


def test_patch_updates_existing_user_correction_rule_case_and_whitespace_insensitively(client):
    # Must reuse categorisation/rules.py's own exact-match semantics (case-insensitive, trimmed —
    # see pattern_matches), not a stricter hand-rolled comparison, or two corrections whose raw
    # descriptions differ only by case/whitespace would wrongly create two overlapping rules.
    api_client, SessionLocal, account_id = client
    tx_id_1 = _seed(SessionLocal, account_id, raw_description="Acme Coffee Roasters 042")
    tx_id_2 = _seed(SessionLocal, account_id, raw_description=" ACME COFFEE ROASTERS 042 ")

    api_client.patch(f"/transactions/{tx_id_1}", json={"category": "Cafes & Restaurants"})
    api_client.patch(f"/transactions/{tx_id_2}", json={"category": "Shopping", "subcategory": "Homeware"})

    with SessionLocal() as session:
        rules = session.query(CategorisationRule).filter(CategorisationRule.source == "user_correction").all()
    assert len(rules) == 1
    assert rules[0].category == "Shopping"
    assert rules[0].subcategory == "Homeware"


def test_patch_rejects_invalid_category(client):
    api_client, SessionLocal, account_id = client
    tx_id = _seed(SessionLocal, account_id)

    response = api_client.patch(f"/transactions/{tx_id}", json={"category": "NotARealCategory"})

    assert response.status_code == 400
    with SessionLocal() as session:
        tx = session.get(Transaction, tx_id)
        assert tx.category == "Miscellaneous"  # unchanged
        assert session.query(CategorisationRule).filter(CategorisationRule.source == "user_correction").count() == 0


def test_patch_rejects_subcategory_not_valid_for_category(client):
    api_client, SessionLocal, account_id = client
    tx_id = _seed(SessionLocal, account_id)

    response = api_client.patch(
        f"/transactions/{tx_id}", json={"category": "Groceries", "subcategory": "Flights"}
    )

    assert response.status_code == 400


def test_patch_unknown_transaction_returns_404(client):
    api_client, _, _ = client

    response = api_client.patch("/transactions/999999", json={"category": "Groceries"})

    assert response.status_code == 404
