from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import bulk_save_transactions, save_transaction
from backend.models import Account, Base, Transaction


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def account(session):
    acc = Account(name="CC", institution="NAB", owner="Rohan", account_type="Credit Card")
    session.add(acc)
    session.commit()
    return acc


def _tx_kwargs(account_id, **overrides):
    base = dict(
        account_id=account_id,
        date=date(2026, 8, 8),
        amount=-38.66,
        raw_description="HILLS MEATS PTY LTDHILLS Forest Hill 036",
        merchant="Hills Meats",
        category="Groceries",
        balance=-4131.90,
    )
    base.update(overrides)
    return base


def test_save_transaction_persists_row(session, account):
    tx = save_transaction(session, **_tx_kwargs(account.id))
    session.commit()
    assert tx.id is not None
    assert session.query(Transaction).count() == 1


def test_bulk_save_skips_exact_duplicate(session, account):
    row = _tx_kwargs(account.id)
    bulk_save_transactions(session, [row])
    session.commit()
    assert session.query(Transaction).count() == 1

    # Re-uploading the same statement should not duplicate the row (FR-3).
    bulk_save_transactions(session, [row])
    session.commit()
    assert session.query(Transaction).count() == 1


def test_bulk_save_keeps_genuinely_different_rows(session, account):
    row1 = _tx_kwargs(account.id)
    row2 = _tx_kwargs(account.id, amount=-71.09)  # same merchant, different amount/day txn
    bulk_save_transactions(session, [row1, row2])
    session.commit()
    assert session.query(Transaction).count() == 2


def test_same_day_same_amount_different_balance_are_not_treated_as_duplicates(session, account):
    # Two genuinely different purchases (e.g. two identical coffees at the same cafe, same day,
    # same amount) have different running balances — the second must not be silently dropped.
    row1 = _tx_kwargs(account.id, balance=-100.00)
    row2 = _tx_kwargs(account.id, balance=-138.66)
    bulk_save_transactions(session, [row1, row2])
    session.commit()
    assert session.query(Transaction).count() == 2


def test_settled_row_arriving_after_pending_supersedes_it(session, account):
    pending = save_transaction(
        session, **_tx_kwargs(account.id, date=date(2026, 8, 5),
                               raw_transaction_type="PURCHASE AUTHORISATION", balance=-100.0)
    )
    session.commit()

    settled = save_transaction(
        session, **_tx_kwargs(account.id, date=date(2026, 8, 8),  # bank moved the date on settlement
                               raw_transaction_type="CREDIT CARD PURCHASE", balance=-138.66)
    )
    session.commit()

    session.refresh(pending)
    assert settled is not None
    assert pending.superseded_by_id == settled.id
    assert settled.superseded_by_id is None
    assert session.query(Transaction).count() == 2  # both kept (NFR-6), only one "active"


def test_pending_row_arriving_after_settled_is_superseded_immediately(session, account):
    settled = save_transaction(
        session, **_tx_kwargs(account.id, date=date(2026, 8, 8),
                               raw_transaction_type="CREDIT CARD PURCHASE", balance=-138.66)
    )
    session.commit()

    pending = save_transaction(
        session, **_tx_kwargs(account.id, date=date(2026, 8, 5),
                               raw_transaction_type="PURCHASE AUTHORISATION", balance=-100.0)
    )
    session.commit()

    assert pending.superseded_by_id == settled.id


def test_settlement_matches_closest_pending_when_multiple_candidates_exist(session, account):
    # Two identical purchases (same merchant/amount) both pending within the window, on different
    # days. When one settles, it must resolve the CLOSEST pending row, not an arbitrary one — the
    # wrong pick would leave the true match still counted as an unresolved active transaction
    # while incorrectly hiding the unrelated one from rollups.
    pending_far = save_transaction(
        session, **_tx_kwargs(account.id, date=date(2026, 8, 1),
                               raw_transaction_type="PURCHASE AUTHORISATION", balance=-100.0)
    )
    session.commit()
    pending_near = save_transaction(
        session, **_tx_kwargs(account.id, date=date(2026, 8, 7),
                               raw_transaction_type="PURCHASE AUTHORISATION", balance=-200.0)
    )
    session.commit()

    settled = save_transaction(
        session, **_tx_kwargs(account.id, date=date(2026, 8, 8),
                               raw_transaction_type="CREDIT CARD PURCHASE", balance=-238.66)
    )
    session.commit()

    session.refresh(pending_far)
    session.refresh(pending_near)
    assert pending_near.superseded_by_id == settled.id
    assert pending_far.superseded_by_id is None


def test_settlement_outside_date_window_does_not_link(session, account):
    # A genuinely separate recurring charge ~30 days later must not be treated as a settlement.
    pending = save_transaction(
        session, **_tx_kwargs(account.id, date=date(2026, 7, 1),
                               raw_transaction_type="PURCHASE AUTHORISATION", balance=-100.0)
    )
    session.commit()

    later = save_transaction(
        session, **_tx_kwargs(account.id, date=date(2026, 8, 1),
                               raw_transaction_type="CREDIT CARD PURCHASE", balance=-238.66)
    )
    session.commit()

    session.refresh(pending)
    assert pending.superseded_by_id is None
    assert later.superseded_by_id is None
    assert session.query(Transaction).count() == 2
