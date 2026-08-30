from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.api as api_module
from backend.models import Account, Base, Transaction, TransferGroup
from backend.needs_review_reasons import (
    LOW_CONFIDENCE_CATEGORY,
    REFUND_AMBIGUITY,
    TRANSFER_MATCH,
    UNRECOGNISED_ACCOUNT,
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test_finance.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(bind=engine)
    monkeypatch.setattr(api_module, "engine", engine)
    monkeypatch.setattr(api_module, "SessionLocal", TestSessionLocal)
    Base.metadata.create_all(bind=engine)

    with TestSessionLocal() as seed:
        a = Account(name="A", institution="NAB", owner="Rohan", account_type="Everyday")
        b = Account(name="B", institution="NAB", owner="Rohan", account_type="Everyday")
        seed.add_all([a, b])
        seed.commit()
        account_ids = (a.id, b.id)

    return TestClient(api_module.app), TestSessionLocal, account_ids


def _seed_tx(SessionLocal, account_id, **overrides):
    defaults = dict(
        account_id=account_id,
        date=date(2026, 8, 5),
        amount=-100.0,
        raw_description="Some transaction",
        category="Miscellaneous",
        subcategory=None,
        type="Expense",
        is_refund=False,
        transfer_group_id=None,
        source="bank_import",
        needs_review=False,
        needs_review_reason=None,
        confidence_score=1.0,
    )
    defaults.update(overrides)
    with SessionLocal() as session:
        tx = Transaction(**defaults)
        session.add(tx)
        session.commit()
        session.refresh(tx)
        return tx.id


def _seed_linked_pair(SessionLocal, account_ids, *, tier, confidence, needs_review):
    a_id, b_id = account_ids
    with SessionLocal() as session:
        group = TransferGroup(detection_tier=tier, confidence=confidence)
        session.add(group)
        session.flush()
        tx_a = Transaction(
            account_id=a_id, date=date(2026, 8, 5), amount=-100.0, raw_description="Out",
            type="Transfer", transfer_group_id=group.id, needs_review=needs_review,
            needs_review_reason=TRANSFER_MATCH if needs_review else None,
        )
        tx_b = Transaction(
            account_id=b_id, date=date(2026, 8, 5), amount=100.0, raw_description="In",
            type="Transfer", transfer_group_id=group.id, needs_review=needs_review,
            needs_review_reason=TRANSFER_MATCH if needs_review else None,
        )
        session.add_all([tx_a, tx_b])
        session.commit()
        return tx_a.id, tx_b.id, group.id


# --- needs_review_reason / transfer_group_id filtering on GET /transactions -------------------

def test_transactions_filterable_by_needs_review_reason(client):
    api_client, SessionLocal, (a, _) = client
    _seed_tx(SessionLocal, a, needs_review=True, needs_review_reason=REFUND_AMBIGUITY)
    _seed_tx(SessionLocal, a, needs_review=True, needs_review_reason=TRANSFER_MATCH)

    body = api_client.get("/transactions", params={"needs_review_reason": REFUND_AMBIGUITY}).json()

    assert len(body) == 1
    assert body[0]["needs_review_reason"] == REFUND_AMBIGUITY


def test_transactions_filterable_by_transfer_group_id(client):
    api_client, SessionLocal, account_ids = client
    tx_a_id, tx_b_id, group_id = _seed_linked_pair(
        SessionLocal, account_ids, tier=2, confidence=0.6, needs_review=True
    )
    _seed_tx(SessionLocal, account_ids[0])  # unrelated row, must not appear

    body = api_client.get("/transactions", params={"transfer_group_id": group_id}).json()

    assert {t["id"] for t in body} == {tx_a_id, tx_b_id}


# --- is_refund correction (refund ambiguity, §1.2) ---------------------------------------------

def test_patch_is_refund_resolves_refund_ambiguity_flag(client):
    api_client, SessionLocal, (a, _) = client
    tx_id = _seed_tx(SessionLocal, a, needs_review=True, needs_review_reason=REFUND_AMBIGUITY)

    body = api_client.patch(f"/transactions/{tx_id}", json={"is_refund": True}).json()

    assert body["is_refund"] is True
    assert body["needs_review"] is False
    assert body["needs_review_reason"] is None


def test_patch_is_refund_false_also_resolves_the_flag(client):
    api_client, SessionLocal, (a, _) = client
    tx_id = _seed_tx(SessionLocal, a, needs_review=True, needs_review_reason=REFUND_AMBIGUITY)

    body = api_client.patch(f"/transactions/{tx_id}", json={"is_refund": False}).json()

    assert body["is_refund"] is False
    assert body["needs_review"] is False


# --- confirm_transfer_match (Tier-2 Medium: already linked) ------------------------------------

def test_confirm_transfer_match_clears_review_flag_on_both_legs(client):
    api_client, SessionLocal, account_ids = client
    tx_a_id, tx_b_id, _ = _seed_linked_pair(SessionLocal, account_ids, tier=2, confidence=0.6, needs_review=True)

    body = api_client.patch(f"/transactions/{tx_a_id}", json={"confirm_transfer_match": True}).json()

    assert body["needs_review"] is False
    assert body["transfer_group_id"] is not None
    with SessionLocal() as session:
        other = session.get(Transaction, tx_b_id)
        assert other.needs_review is False
        assert other.needs_review_reason is None


def test_confirm_transfer_match_preserves_a_sibling_legs_unrelated_reason(client):
    # /code-review finding: confirming one leg's transfer match must not silently wipe a sibling
    # leg's unrelated, still-unresolved reason (e.g. unrecognised_account).
    api_client, SessionLocal, account_ids = client
    tx_a_id, tx_b_id, _ = _seed_linked_pair(SessionLocal, account_ids, tier=2, confidence=0.6, needs_review=True)
    with SessionLocal() as session:
        other = session.get(Transaction, tx_b_id)
        other.needs_review_reason = UNRECOGNISED_ACCOUNT
        session.commit()

    api_client.patch(f"/transactions/{tx_a_id}", json={"confirm_transfer_match": True})

    with SessionLocal() as session:
        other = session.get(Transaction, tx_b_id)
        assert other.needs_review is True
        assert other.needs_review_reason == UNRECOGNISED_ACCOUNT


def test_confirm_transfer_match_without_a_link_is_rejected(client):
    api_client, SessionLocal, (a, _) = client
    tx_id = _seed_tx(SessionLocal, a)

    response = api_client.patch(f"/transactions/{tx_id}", json={"confirm_transfer_match": True})

    assert response.status_code == 400


# --- confirm_transfer_with_id (Tier-2 Low: suggestion only, not yet linked) --------------------

def test_confirm_transfer_with_id_links_both_legs_at_full_confidence(client):
    api_client, SessionLocal, (a, b) = client
    tx_a_id = _seed_tx(SessionLocal, a, amount=-100.0, type="Expense",
                        needs_review=True, needs_review_reason=TRANSFER_MATCH)
    tx_b_id = _seed_tx(SessionLocal, b, amount=101.5, type="Income",
                        needs_review=True, needs_review_reason=TRANSFER_MATCH)

    body = api_client.patch(
        f"/transactions/{tx_a_id}", json={"confirm_transfer_with_id": tx_b_id}
    ).json()

    assert body["type"] == "Transfer"
    assert body["needs_review"] is False
    assert body["transfer_group_id"] is not None
    with SessionLocal() as session:
        other = session.get(Transaction, tx_b_id)
        assert other.type == "Transfer"
        assert other.needs_review is False
        assert other.transfer_group_id == body["transfer_group_id"]
        group = session.get(TransferGroup, other.transfer_group_id)
        assert group.detection_tier == 2
        assert group.confidence == 1.0


def test_confirm_transfer_with_id_unknown_counterpart_404s(client):
    api_client, SessionLocal, (a, _) = client
    tx_id = _seed_tx(SessionLocal, a)

    response = api_client.patch(f"/transactions/{tx_id}", json={"confirm_transfer_with_id": 999999})

    assert response.status_code == 404


def test_confirm_transfer_with_id_already_linked_transaction_is_rejected(client):
    api_client, SessionLocal, account_ids = client
    tx_a_id, _, _ = _seed_linked_pair(SessionLocal, account_ids, tier=2, confidence=0.6, needs_review=True)
    other_id = _seed_tx(SessionLocal, account_ids[0])

    response = api_client.patch(f"/transactions/{tx_a_id}", json={"confirm_transfer_with_id": other_id})

    assert response.status_code == 400


def test_confirm_transfer_with_id_rejects_itself_as_counterpart(client):
    # /code-review finding: a transaction confirming itself as its own transfer counterpart would
    # otherwise pass every other check and produce a group with only one real member.
    api_client, SessionLocal, (a, _) = client
    tx_id = _seed_tx(SessionLocal, a, needs_review=True, needs_review_reason=TRANSFER_MATCH)

    response = api_client.patch(f"/transactions/{tx_id}", json={"confirm_transfer_with_id": tx_id})

    assert response.status_code == 400


def test_confirm_transfer_with_id_rejects_a_same_account_counterpart(client):
    api_client, SessionLocal, (a, _) = client
    tx_id = _seed_tx(SessionLocal, a, amount=-100.0, needs_review=True, needs_review_reason=TRANSFER_MATCH)
    same_account_other_id = _seed_tx(SessionLocal, a, amount=100.0)

    response = api_client.patch(
        f"/transactions/{tx_id}", json={"confirm_transfer_with_id": same_account_other_id}
    )

    assert response.status_code == 400


def test_confirm_transfer_with_id_rejects_a_same_sign_counterpart(client):
    api_client, SessionLocal, (a, b) = client
    tx_id = _seed_tx(SessionLocal, a, amount=-100.0, needs_review=True, needs_review_reason=TRANSFER_MATCH)
    same_sign_other_id = _seed_tx(SessionLocal, b, amount=-100.0)  # also a debit, not opposite

    response = api_client.patch(f"/transactions/{tx_id}", json={"confirm_transfer_with_id": same_sign_other_id})

    assert response.status_code == 400


# --- PATCH request validation -------------------------------------------------------------------

def test_patch_with_no_action_specified_is_rejected(client):
    api_client, SessionLocal, (a, _) = client
    tx_id = _seed_tx(SessionLocal, a)

    response = api_client.patch(f"/transactions/{tx_id}", json={})

    assert response.status_code == 400


def test_patch_with_unknown_field_is_rejected(client):
    # extra="forbid" — a typo'd/unrecognised field must fail loudly, not be silently dropped and
    # return 200 with nothing actually changed.
    api_client, SessionLocal, (a, _) = client
    tx_id = _seed_tx(SessionLocal, a)

    response = api_client.patch(f"/transactions/{tx_id}", json={"catgory": "Groceries"})

    assert response.status_code == 422


# --- reject_transfer_match -----------------------------------------------------------------

def test_reject_transfer_match_unlinks_an_auto_tagged_pair_and_reverts_type(client):
    api_client, SessionLocal, account_ids = client
    tx_a_id, tx_b_id, group_id = _seed_linked_pair(
        SessionLocal, account_ids, tier=2, confidence=0.6, needs_review=True
    )

    body = api_client.patch(f"/transactions/{tx_a_id}", json={"reject_transfer_match": True}).json()

    assert body["type"] == "Expense"  # amount was -100.0
    assert body["transfer_group_id"] is None
    assert body["needs_review"] is False
    with SessionLocal() as session:
        other = session.get(Transaction, tx_b_id)
        assert other.type == "Income"  # amount was +100.0
        assert other.transfer_group_id is None
        assert other.needs_review is False
        assert session.get(TransferGroup, group_id) is None  # orphaned group cleaned up


def test_reject_transfer_match_preserves_a_sibling_legs_unrelated_reason(client):
    api_client, SessionLocal, account_ids = client
    tx_a_id, tx_b_id, _ = _seed_linked_pair(SessionLocal, account_ids, tier=2, confidence=0.6, needs_review=True)
    with SessionLocal() as session:
        other = session.get(Transaction, tx_b_id)
        other.needs_review_reason = UNRECOGNISED_ACCOUNT
        session.commit()

    api_client.patch(f"/transactions/{tx_a_id}", json={"reject_transfer_match": True})

    with SessionLocal() as session:
        other = session.get(Transaction, tx_b_id)
        # Unlinked (reverted to a plain Income row) but the unrelated account concern survives.
        assert other.transfer_group_id is None
        assert other.needs_review is True
        assert other.needs_review_reason == UNRECOGNISED_ACCOUNT


def test_reject_transfer_match_on_an_unlinked_suggestion_just_clears_the_flag(client):
    api_client, SessionLocal, (a, _) = client
    tx_id = _seed_tx(SessionLocal, a, type="Expense", needs_review=True, needs_review_reason=TRANSFER_MATCH)

    body = api_client.patch(f"/transactions/{tx_id}", json={"reject_transfer_match": True}).json()

    assert body["type"] == "Expense"  # untouched
    assert body["transfer_group_id"] is None
    assert body["needs_review"] is False


def test_reject_transfer_match_on_an_unlinked_suggestion_preserves_a_still_live_reason(client):
    # Dismissing a Low suggestion doesn't touch this row's own category/type, so an existing
    # low_confidence_category flag (already preserved by transfers/detection.py, since Low never
    # supersedes it) must stay exactly as live as it was.
    api_client, SessionLocal, (a, _) = client
    tx_id = _seed_tx(
        SessionLocal, a, type="Expense", needs_review=True, needs_review_reason=LOW_CONFIDENCE_CATEGORY
    )

    body = api_client.patch(f"/transactions/{tx_id}", json={"reject_transfer_match": True}).json()

    assert body["needs_review"] is True
    assert body["needs_review_reason"] == LOW_CONFIDENCE_CATEGORY


# --- GET /transactions/{id}/suggested-transfer-match --------------------------------------------

def test_suggested_transfer_match_returns_the_best_current_candidate(client):
    api_client, SessionLocal, (a, b) = client
    tx_a_id = _seed_tx(SessionLocal, a, date=date(2026, 8, 5), amount=-100.0,
                        needs_review=True, needs_review_reason=TRANSFER_MATCH)
    tx_b_id = _seed_tx(SessionLocal, b, date=date(2026, 8, 7), amount=101.5,
                        needs_review=True, needs_review_reason=TRANSFER_MATCH)

    body = api_client.get(f"/transactions/{tx_a_id}/suggested-transfer-match").json()

    assert body is not None
    assert body["id"] == tx_b_id


def test_suggested_transfer_match_returns_null_for_an_already_linked_transaction(client):
    # /code-review finding: calling this on an already-linked row (its own docstring says it's
    # only for the not-yet-linked case) must not surface an unrelated transaction as a false
    # suggestion.
    api_client, SessionLocal, account_ids = client
    tx_a_id, _, _ = _seed_linked_pair(SessionLocal, account_ids, tier=2, confidence=0.6, needs_review=True)
    # An unrelated, unlinked transaction that would otherwise look like a plausible candidate.
    _seed_tx(SessionLocal, account_ids[1], date=date(2026, 8, 5), amount=100.0)

    response = api_client.get(f"/transactions/{tx_a_id}/suggested-transfer-match")

    assert response.status_code == 200
    assert response.json() is None


def test_suggested_transfer_match_returns_null_when_none_exists(client):
    api_client, SessionLocal, (a, _) = client
    tx_id = _seed_tx(SessionLocal, a)

    response = api_client.get(f"/transactions/{tx_id}/suggested-transfer-match")

    assert response.status_code == 200
    assert response.json() is None


def test_suggested_transfer_match_unknown_transaction_404s(client):
    api_client, _, _ = client

    response = api_client.get("/transactions/999999/suggested-transfer-match")

    assert response.status_code == 404
