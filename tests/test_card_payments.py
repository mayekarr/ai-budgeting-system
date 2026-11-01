from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Account, Base, Transaction
from transfers.card_payments import is_card_payment, reclassify_card_payments


@pytest.mark.parametrize("description, amount", [
    ("DIRECT DEBIT PAYMENT", 10749.45),
    ("  direct debit payment ", 50.0),
    ("4530307001277128 NAB CARD AUTOPAY MRS ANILA ROHAN", -7361.28),
])
def test_card_payment_signals(description, amount):
    assert is_card_payment(description, amount) is True


@pytest.mark.parametrize("description, amount", [
    ("DIRECT DEBIT PAYMENT", -50.0),                # a debit is not the card-side credit
    ("4530307001277128 NAB CARD AUTOPAY", 50.0),    # a credit is not the paying-side debit
    ("DIRECT DEBIT PAYMENT TO TELSTRA", 99.0),      # must be the bare phrase
    ("WOOLWORTHS", 12.0),
])
def test_ordinary_rows_are_not_card_payments(description, amount):
    assert is_card_payment(description, amount) is False


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        s.add(Account(name="CC"))
        s.commit()
        yield s


def _tx(session, description, amount, **kw):
    tx = Transaction(account_id=session.query(Account).one().id, date=date(2026, 10, 6), amount=amount,
                     raw_description=description, type=kw.pop("type", "Income"), category="Miscellaneous",
                     needs_review=True, needs_review_reason="llm_unavailable", **kw)
    session.add(tx)
    session.commit()
    return tx


def test_reclassify_types_a_lone_card_payment_as_transfer_and_clears_its_flag_and_category(session):
    tx = _tx(session, "DIRECT DEBIT PAYMENT", 10749.45)
    assert reclassify_card_payments(session) == 1
    session.refresh(tx)
    assert tx.type == "Transfer" and tx.category is None and tx.subcategory is None
    assert tx.needs_review is False and tx.transfer_group_id is None


def test_reclassify_is_idempotent_and_ignores_ordinary_rows(session):
    other = _tx(session, "WOOLWORTHS", 12.0)
    _tx(session, "DIRECT DEBIT PAYMENT", 10749.45)
    reclassify_card_payments(session)
    assert reclassify_card_payments(session) == 0
    session.refresh(other)
    assert other.type == "Income"
