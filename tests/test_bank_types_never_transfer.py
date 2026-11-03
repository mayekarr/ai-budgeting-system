from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Account, Base, Transaction
from transfers.detection import process_transfer_detection


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s


@pytest.mark.parametrize("bank_type", ["BPAY", "DIRECT DEBIT"])
def test_a_payment_to_a_third_party_never_pairs_with_an_equal_credit_elsewhere(session, bank_type):
    # Macquarie's BPAY payments and direct debits go to other people, so an equal credit on another
    # account (a refund, a share-sale payout) must not turn them into a transfer.
    mac, rc = Account(name="MAC"), Account(name="RC")
    session.add_all([mac, rc])
    session.flush()
    payment = Transaction(account_id=mac.id, date=date(2026, 8, 14), amount=-550.0, raw_description="Bpay To Someone",
                          raw_transaction_type=bank_type)
    credit = Transaction(account_id=rc.id, date=date(2026, 8, 14), amount=550.0, raw_description="Refund",
                         raw_transaction_type="TRANSFER CREDIT")
    session.add_all([payment, credit])
    session.commit()

    process_transfer_detection(session, payment)
    process_transfer_detection(session, credit)

    assert payment.transfer_group_id is None and credit.transfer_group_id is None
    assert payment.type != "Transfer" and credit.type != "Transfer"
