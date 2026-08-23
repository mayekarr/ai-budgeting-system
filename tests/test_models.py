from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Account, AccountAlias, Base, CategorisationRule, Transaction, TransferGroup


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s


def test_account_and_alias_resolve_to_same_account(session):
    account = Account(name="Rohan's Classic", institution="NAB", owner="Rohan", account_type="Everyday")
    session.add(account)
    session.flush()

    alias = AccountAlias(account_id=account.id, raw_identifier="133500607")
    session.add(alias)
    session.commit()

    fetched = session.query(AccountAlias).filter_by(raw_identifier="133500607").one()
    assert fetched.account_id == account.id
    assert fetched.account.name == "Rohan's Classic"


def test_account_alias_raw_identifier_is_unique(session):
    account = Account(name="A", institution="NAB", owner="Rohan", account_type="Everyday")
    session.add(account)
    session.flush()
    session.add(AccountAlias(account_id=account.id, raw_identifier="dup"))
    session.commit()

    session.add(AccountAlias(account_id=account.id, raw_identifier="dup"))
    with pytest.raises(Exception):
        session.commit()


def test_transaction_defaults(session):
    account = Account(name="CC", institution="NAB", owner="Rohan", account_type="Credit Card")
    session.add(account)
    session.flush()

    tx = Transaction(
        account_id=account.id,
        date=date(2026, 8, 8),
        amount=-38.66,
        raw_description="HILLS MEATS PTY LTDHILLS Forest Hill 036",
    )
    session.add(tx)
    session.commit()

    assert tx.type == "Expense"
    assert tx.is_refund is False
    assert tx.needs_review is False
    assert tx.source == "bank_import"
    assert tx.transfer_group_id is None
    assert tx.category is None


def test_transfer_group_links_multiple_transactions(session):
    account = Account(name="CC", institution="NAB", owner="Rohan", account_type="Credit Card")
    session.add(account)
    session.flush()

    group = TransferGroup(detection_tier=1, confidence=1.0)
    session.add(group)
    session.flush()

    tx1 = Transaction(account_id=account.id, date=date(2026, 8, 5), amount=8050.20,
                       raw_description="DIRECT DEBIT PAYMENT", type="Transfer", transfer_group_id=group.id)
    tx2 = Transaction(account_id=account.id, date=date(2026, 8, 5), amount=-8050.20,
                       raw_description="NAB CARD AUTOPAY", type="Transfer", transfer_group_id=group.id)
    session.add_all([tx1, tx2])
    session.commit()

    members = session.query(Transaction).filter_by(transfer_group_id=group.id).all()
    assert len(members) == 2


def test_categorisation_rule_fields(session):
    rule = CategorisationRule(
        pattern="WOOLWORTHS", match_type="substring", category="Groceries",
        subcategory=None, priority=10, source="seeded", is_active=True,
    )
    session.add(rule)
    session.commit()

    fetched = session.query(CategorisationRule).filter_by(pattern="WOOLWORTHS").one()
    assert fetched.category == "Groceries"
    assert fetched.is_active is True
