from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Account, AccountAlias, Base, Transaction
from transfers.detection import process_transfer_detection

DEBIT_TEXT = "ANILA ROHAN MAYEKAR Y2374176428 Macquarie CM Acc"
CREDIT_TEXT = "Mr Rohan Ashok Mayekar Macquarie Cm Acc"


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s


def _account(session, name):
    account = Account(name=name)
    session.add(account)
    session.commit()
    return account


def _macquarie(session, name):
    """An account whose statement names it as a Macquarie account (the alias the MAC export gives)."""
    account = _account(session, name)
    session.add(AccountAlias(account_id=account.id, raw_identifier=f"Macquarie Cash Management Account {name}"))
    session.commit()
    return account


def _lone_debit(session, account, d, amount, text=DEBIT_TEXT):
    """A debit to the user's Macquarie account, typed Transfer by its text with no group (FR-9k)."""
    tx = Transaction(account_id=account.id, date=d, amount=amount, raw_description=text, type="Transfer",
                     raw_transaction_type="TRANSFER DEBIT", raw_bank_category="Transfers out")
    session.add(tx)
    session.commit()
    return tx


def _macquarie_credit(session, account, d, amount, text=CREDIT_TEXT):
    tx = Transaction(account_id=account.id, date=d, amount=amount, raw_description=text, type="Income",
                     raw_transaction_type="TRANSFER CREDIT")
    session.add(tx)
    session.commit()
    return tx


def test_a_macquarie_credit_pairs_with_the_lone_debit_that_sent_it(session):
    nab, mac = _account(session, "RC"), _macquarie(session, "MAC")
    debit = _lone_debit(session, nab, date(2026, 8, 20), -4800.0)
    credit = _macquarie_credit(session, mac, date(2026, 8, 20), 4800.0)

    process_transfer_detection(session, credit)

    assert debit.transfer_group_id is not None and debit.transfer_group_id == credit.transfer_group_id
    assert credit.type == "Transfer"


def test_the_debit_arriving_after_the_macquarie_file_finds_its_credit(session):
    nab, mac = _account(session, "RC"), _macquarie(session, "MAC")
    credit = _macquarie_credit(session, mac, date(2026, 8, 20), 4800.0)
    debit = _lone_debit(session, nab, date(2026, 8, 20), -4800.0)

    process_transfer_detection(session, debit)

    assert debit.transfer_group_id is not None and debit.transfer_group_id == credit.transfer_group_id


def test_a_lone_debit_pairs_only_on_the_exact_amount(session):
    nab, mac = _account(session, "RC"), _macquarie(session, "MAC")
    debit = _lone_debit(session, nab, date(2026, 8, 20), -4800.0)
    credit = _macquarie_credit(session, mac, date(2026, 8, 20), 4799.0)

    process_transfer_detection(session, credit)

    assert debit.transfer_group_id is None and credit.type == "Income"


def test_a_lone_debit_pairs_within_the_date_window_not_beyond_it(session):
    nab, mac = _account(session, "RC"), _macquarie(session, "MAC")
    debit = _lone_debit(session, nab, date(2026, 8, 10), -4800.0)
    credit = _macquarie_credit(session, mac, date(2026, 8, 20), 4800.0)

    process_transfer_detection(session, credit)

    assert debit.transfer_group_id is None


def test_a_card_payment_transfer_is_still_never_a_heuristic_partner(session):
    # Only a debit to the user's own Macquarie account may be taken as a partner; any other groupless
    # Transfer is already settled by its text and stays out of amount-and-date matching.
    nab, other = _account(session, "JC"), _account(session, "AC")
    settled = _lone_debit(session, nab, date(2026, 8, 20), -300.0, text="NAB CARD AUTOPAY")
    candidate = Transaction(account_id=other.id, date=date(2026, 8, 20), amount=300.0, raw_description="Gift",
                            type="Income", raw_transaction_type="TRANSFER CREDIT")
    session.add(candidate)
    session.commit()

    process_transfer_detection(session, candidate)

    assert settled.transfer_group_id is None and candidate.type == "Income"


def test_a_group_is_still_exactly_two_rows(session):
    nab, mac = _account(session, "RC"), _macquarie(session, "MAC")
    debit = _lone_debit(session, nab, date(2026, 8, 20), -4800.0)
    first = _macquarie_credit(session, mac, date(2026, 8, 20), 4800.0)
    second = _macquarie_credit(session, mac, date(2026, 8, 21), 4800.0)

    process_transfer_detection(session, first)
    process_transfer_detection(session, second)

    assert first.transfer_group_id is not None and first.transfer_group_id == debit.transfer_group_id
    assert second.transfer_group_id is None and second.type == "Income"


def test_a_lone_debit_never_pairs_with_a_credit_on_a_non_macquarie_account(session):
    # The debit says it went to Macquarie, so its partner must be on a Macquarie account: a friend's
    # repayment of the same amount on another NAB account is not it.
    nab, other = _account(session, "RC"), _account(session, "AC")
    debit = _lone_debit(session, nab, date(2026, 8, 20), -4800.0)
    repayment = _macquarie_credit(session, other, date(2026, 8, 20), 4800.0, text="Friend repaying")

    process_transfer_detection(session, repayment)   # searching from the credit side
    process_transfer_detection(session, debit)       # and from the debit side

    assert debit.transfer_group_id is None and repayment.transfer_group_id is None
    assert repayment.type == "Income"


def _plain_debit(session, account, d, amount, text):
    """An ordinary NAB payment out (not worded as going to Macquarie), as the bank reports a transfer."""
    tx = Transaction(account_id=account.id, date=d, amount=amount, raw_description=text, type="Expense",
                     raw_transaction_type="TRANSFER DEBIT", raw_bank_category="Transfers out")
    session.add(tx)
    session.commit()
    return tx


def test_a_macquarie_credit_does_not_pair_with_a_payment_that_names_nobody_in_the_household(session):
    # A third party's payment into MAC and an equal payment Rohan makes to a friend are not one transfer.
    nab, mac = _account(session, "AC"), _macquarie(session, "MAC")
    payment = _plain_debit(session, nab, date(2026, 8, 20), -2000.0, "JOHN SMITH K1234567890 rent share")
    credit = _macquarie_credit(session, mac, date(2026, 8, 20), 2000.0, text="Acme Pty Ltd")

    process_transfer_detection(session, credit)

    assert payment.transfer_group_id is None and credit.type == "Income"


def test_a_macquarie_credit_still_pairs_with_a_payment_to_a_household_member(session):
    # Real pairs read like 'ROHAN MAYEKAR ANILA K9845859487' on the NAB side (the payee is the owner).
    nab, mac = _account(session, "AC"), _macquarie(session, "MAC")
    payment = _plain_debit(session, nab, date(2026, 8, 20), -2000.0, "ROHAN MAYEKAR ANILA K9845859487")
    credit = _macquarie_credit(session, mac, date(2026, 8, 20), 2000.0)

    process_transfer_detection(session, credit)

    assert payment.transfer_group_id is not None and payment.transfer_group_id == credit.transfer_group_id


def test_two_macquarie_accounts_pair_without_any_wording(session):
    mac, accelerator = _macquarie(session, "MAC"), _macquarie(session, "MACACC")
    out = Transaction(account_id=mac.id, date=date(2026, 8, 20), amount=-2000.0, raw_description="To someone",
                      type="Expense", raw_transaction_type="TRANSFER DEBIT")
    session.add(out)
    session.commit()
    into = _macquarie_credit(session, accelerator, date(2026, 8, 20), 2000.0, text="From someone")

    process_transfer_detection(session, into)

    assert out.transfer_group_id is not None and out.transfer_group_id == into.transfer_group_id


def test_an_account_is_macquarie_by_its_institution_too(session):
    nab = _account(session, "RC")
    mac = _account(session, "Savings")
    mac.institution = "Macquarie"
    session.commit()
    debit = _lone_debit(session, nab, date(2026, 8, 20), -4800.0)
    credit = _macquarie_credit(session, mac, date(2026, 8, 20), 4800.0)

    process_transfer_detection(session, credit)

    assert debit.transfer_group_id is not None and debit.transfer_group_id == credit.transfer_group_id


def test_identical_lone_debits_against_identical_macquarie_credits_are_an_interchangeable_tie(session):
    # Two identical $5,000 payments to Macquarie on one day against two identical $5,000 credits there:
    # every pairing is equally right, so nothing is downgraded or flagged (same rule as ordinary rows).
    nab, mac = _account(session, "RC"), _macquarie(session, "MAC")
    debits = [_lone_debit(session, nab, date(2026, 8, 20), -5000.0) for _ in range(2)]
    credits = [_macquarie_credit(session, mac, date(2026, 8, 20), 5000.0) for _ in range(2)]

    for debit in debits:
        process_transfer_detection(session, debit)

    assert all(c.transfer_group_id is not None for c in credits)
    assert all(d.transfer_group_id is not None for d in debits)
    assert not any(r.needs_review for r in [*debits, *credits])
