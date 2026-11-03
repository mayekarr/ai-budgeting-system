from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Account, AccountAlias, Base, Transaction
from transfers.repair import rebuild_transfer_groups


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s


def _account(session, name, alias=None):
    account = Account(name=name)
    session.add(account)
    session.flush()
    if alias:
        session.add(AccountAlias(account_id=account.id, raw_identifier=alias))
    return account


def test_a_rebuild_pairs_a_lone_macquarie_debit_with_a_credit_already_imported(session):
    rc = _account(session, "RC")
    mac = _account(session, "MAC", alias="Macquarie Cash Management Account")
    debit = Transaction(account_id=rc.id, date=date(2026, 8, 20), amount=-4800.0, type="Transfer",
                        raw_description="ANILA ROHAN MAYEKAR Y2374176428 Macquarie CM Acc",
                        raw_transaction_type="TRANSFER DEBIT", raw_bank_category="Transfers out")
    credit = Transaction(account_id=mac.id, date=date(2026, 8, 20), amount=4800.0, type="Income",
                         raw_description="Mr Rohan Ashok Mayekar Macquarie Cm Acc",
                         raw_transaction_type="TRANSFER CREDIT")
    session.add_all([debit, credit])
    session.commit()

    rebuild_transfer_groups(session)

    assert debit.transfer_group_id is not None and debit.transfer_group_id == credit.transfer_group_id
