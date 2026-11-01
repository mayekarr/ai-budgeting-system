from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Account, Base, Transaction
from transfers.own_accounts import is_own_account_transfer, reclassify_own_account_transfers


@pytest.mark.parametrize("description, amount", [
    ("Anila RohanMayekar RA6843360794 JC to Macquarie JC", -100000.0),
    ("ANILA ROHANMAYEKAR D1452399069 JC to Mac CMA", -100000.0),
    ("ANILA ROHANMAYEKAR X6375879193 AC to MCA", -100000.0),
    ("ANILA ROHAN MAYEKAR V9037638368 Macquarie CM Acc", -5000.0),
    ("ROHAN MAYEKAR ANILA B3910879342 transfer to mac acc", -5100.0),
    ("ANILA ROHANMAYEKAR M123 JC to Macquarie Bank", -2000.0),
])
def test_a_debit_sent_to_the_users_macquarie_account_is_a_transfer_by_its_text(description, amount):
    assert is_own_account_transfer(description, amount) is True


@pytest.mark.parametrize("description, amount", [
    ("ANILA ROHANMAYEKAR D1452399069 JC to Mac CMA", 100000.0),     # a credit: that leg pairs once MAC is imported
    ("MACQUARIE UNIVERSITY FEES", -500.0),
    ("WOOLWORTHS", -12.0),
    ("PAYMENT TO MCAFEE", -20.0),
    ("BPAY to Macquarie University 1234567", -500.0),           # a payee, not the user's own account
    ("Payment to Macquarie Group Limited", -250.0),
    ("JC to Macquarie University fees", -900.0),
])
def test_other_rows_are_not(description, amount):
    assert is_own_account_transfer(description, amount) is False


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        s.add(Account(name="JC"))
        s.commit()
        yield s


def test_reclassify_types_them_as_transfer_and_is_idempotent(session):
    tx = Transaction(account_id=session.query(Account).one().id, date=date(2025, 12, 10), amount=-100000.0,
                     raw_description="ANILA ROHANMAYEKAR M4535156818 JC to Macquarie", type="Expense",
                     category="Miscellaneous", needs_review=True, needs_review_reason="llm_unavailable")
    session.add(tx)
    session.commit()
    assert reclassify_own_account_transfers(session) == 1
    assert (tx.type, tx.category, tx.needs_review) == ("Transfer", None, False)
    assert reclassify_own_account_transfers(session) == 0
