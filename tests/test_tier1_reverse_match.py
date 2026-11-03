from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Account, AccountAlias, Base, Transaction
from transfers.detection import process_transfer_detection


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
    session.commit()
    return account


def _tx(session, account, d, amount, text, bank_type):
    tx = Transaction(account_id=account.id, date=d, amount=amount, raw_description=text,
                     raw_transaction_type=bank_type, type="Income" if amount > 0 else "Expense")
    session.add(tx)
    session.commit()
    return tx


def test_a_credit_arriving_later_pairs_with_the_earlier_debit_that_names_its_account(session):
    # The debit's text names the destination's account number; the credit's own text names nothing.
    # Whichever statement is uploaded first, the number must still link the two.
    source = _account(session, "SRC")
    dest = _account(session, "DEST", alias="000942290974")
    debit = _tx(session, source, date(2026, 9, 28), -5100.0, "To SOMEONE A/C: 000942290974", "TRANSFER DEBIT")
    credit = _tx(session, dest, date(2026, 9, 28), 5100.0, "From SOMEONE", "TRANSFER CREDIT")

    process_transfer_detection(session, credit)

    assert debit.transfer_group_id is not None and debit.transfer_group_id == credit.transfer_group_id
    assert credit.type == debit.type == "Transfer"
    assert debit.transfer_group.detection_tier == 1


def test_the_account_number_match_overrides_an_earlier_amount_and_date_pairing(session):
    source = _account(session, "SRC")
    dest = _account(session, "DEST", alias="000942290974")
    other = _account(session, "OTHER")
    debit = _tx(session, source, date(2026, 9, 28), -5100.0, "To SOMEONE A/C: 000942290974", "TRANSFER DEBIT")
    wrong = _tx(session, other, date(2026, 9, 28), 5100.0, "transfer salary", "TRANSFER CREDIT")
    process_transfer_detection(session, debit)          # the destination is not imported yet: Tier 2 picks the wrong credit
    assert debit.transfer_group.detection_tier == 2 and wrong.transfer_group_id == debit.transfer_group_id
    credit = _tx(session, dest, date(2026, 9, 28), 5100.0, "From SOMEONE", "TRANSFER CREDIT")

    process_transfer_detection(session, credit, tiers=(1,))

    assert debit.transfer_group.detection_tier == 1 and debit.transfer_group_id == credit.transfer_group_id
    assert wrong.transfer_group_id is None


def test_a_different_amount_or_a_distant_date_does_not_match(session):
    source = _account(session, "SRC")
    dest = _account(session, "DEST", alias="000942290974")
    debit = _tx(session, source, date(2026, 9, 28), -5100.0, "To SOMEONE A/C: 000942290974", "TRANSFER DEBIT")
    off_amount = _tx(session, dest, date(2026, 9, 28), 5099.0, "From SOMEONE", "TRANSFER CREDIT")
    too_late = _tx(session, dest, date(2026, 10, 20), 5100.0, "From SOMEONE", "TRANSFER CREDIT")

    process_transfer_detection(session, off_amount, tiers=(1,))
    process_transfer_detection(session, too_late, tiers=(1,))

    assert debit.transfer_group_id is None


def test_a_debit_that_does_not_name_the_account_is_not_taken_by_the_reverse_match(session):
    source = _account(session, "SRC")
    dest = _account(session, "DEST", alias="000942290974")
    unrelated = _tx(session, source, date(2026, 9, 28), -5100.0, "To SOMEONE ELSE", "TRANSFER DEBIT")
    credit = _tx(session, dest, date(2026, 9, 28), 5100.0, "From SOMEONE", "TRANSFER CREDIT")

    process_transfer_detection(session, credit, tiers=(1,))

    assert unrelated.transfer_group_id is None
