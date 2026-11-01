from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Account, Base, Transaction
from ingestion.bank_category_backfill import backfill_bank_category
from ingestion.nab_format import ParsedRow


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        s.add_all([Account(name="JC"), Account(name="AC")])
        s.commit()
        yield s


def _row(d, amount, desc, category):
    return ParsedRow(date=d, amount=amount, account_identifier="x", raw_transaction_type="",
                     raw_description=desc, balance=None, raw_bank_category=category)


def _tx(session, account_name, d, amount, desc):
    account = session.query(Account).filter_by(name=account_name).one()
    tx = Transaction(account_id=account.id, date=d, amount=amount, raw_description=desc)
    session.add(tx)
    session.commit()
    return tx


def test_fills_in_the_banks_category_by_date_amount_and_description(session):
    jc = _tx(session, "JC", date(2026, 5, 11), -30.0, "ONLINE N6414309103 Arvan food")
    ac = _tx(session, "AC", date(2026, 5, 11), 30.0, "ONLINE N6414309103 Arvan food")
    files = {
        "JC": [_row(date(2026, 5, 11), -30.0, "ONLINE N6414309103 Arvan food", "Internal transfers")],
        "AC": [_row(date(2026, 5, 11), 30.0, "ONLINE N6414309103 Arvan food", "Internal transfers")],
    }
    assert backfill_bank_category(session, files) == 2
    assert jc.raw_bank_category == ac.raw_bank_category == "Internal transfers"


def test_a_row_with_no_match_or_no_bank_category_is_left_alone(session):
    tx = _tx(session, "JC", date(2026, 5, 11), -30.0, "MANUAL ENTRY")
    files = {"JC": [_row(date(2026, 5, 12), -99.0, "SOMETHING ELSE", "Groceries"),
                    _row(date(2026, 5, 11), -30.0, "MANUAL ENTRY", None)]}
    assert backfill_bank_category(session, files) == 0
    assert tx.raw_bank_category is None


def test_the_same_key_in_two_accounts_is_resolved_by_which_file_it_came_from(session):
    # Two accounts can hold a same-day, same-amount, same-wording row; each takes its own file's label.
    jc = _tx(session, "JC", date(2026, 5, 11), -30.0, "SAME TEXT")
    ac = _tx(session, "AC", date(2026, 5, 11), -30.0, "SAME TEXT")
    files = {"JC": [_row(date(2026, 5, 11), -30.0, "SAME TEXT", "Internal transfers"),
                    _row(date(2026, 5, 1), -1.0, "JC ONLY", "Cash")],
             "AC": [_row(date(2026, 5, 11), -30.0, "SAME TEXT", "Donations"),
                    _row(date(2026, 5, 2), -2.0, "AC ONLY", "Cash")]}
    _tx(session, "JC", date(2026, 5, 1), -1.0, "JC ONLY")
    _tx(session, "AC", date(2026, 5, 2), -2.0, "AC ONLY")
    backfill_bank_category(session, files)
    assert jc.raw_bank_category == "Internal transfers" and ac.raw_bank_category == "Donations"


def test_it_never_overwrites_a_category_already_stored_and_is_idempotent(session):
    tx = _tx(session, "JC", date(2026, 5, 11), -30.0, "X")
    tx.raw_bank_category = "Groceries"
    files = {"JC": [_row(date(2026, 5, 11), -30.0, "X", "Internal transfers")]}
    assert backfill_bank_category(session, files) == 0
    assert tx.raw_bank_category == "Groceries"
