from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Account, Base, Transaction, TransferGroup
from transfers.cleanup import clear_transfer_categories


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        s.add(Account(name="JC"))
        s.commit()
        yield s


def _tx(session, tx_type, group=None):
    tx = Transaction(account_id=session.query(Account).one().id, date=date(2026, 1, 1), amount=-10.0,
                     raw_description="X", type=tx_type, category="Miscellaneous", subcategory="Other",
                     transfer_group=group)
    session.add(tx)
    session.commit()
    return tx


def _group(session, confidence, tier=2):
    group = TransferGroup(detection_tier=tier, confidence=confidence)
    session.add(group)
    session.commit()
    return group


def test_tier1_and_groupless_transfers_lose_their_stale_category(session):
    grouped = _tx(session, "Transfer", _group(session, 1.0, tier=1))
    lone = _tx(session, "Transfer")
    assert clear_transfer_categories(session) == 2
    for tx in (grouped, lone):
        session.refresh(tx)
        assert tx.category is None and tx.subcategory is None


def test_tier2_pairs_and_non_transfers_keep_their_category(session):
    # Tier 2 is amount-and-date only, so a stronger match can still send the row back to income/expense.
    tentative = _tx(session, "Transfer", _group(session, 0.6))
    confident_tier2 = _tx(session, "Transfer", _group(session, 1.0))
    expense = _tx(session, "Expense")
    assert clear_transfer_categories(session) == 0
    for tx in (tentative, confident_tier2, expense):
        session.refresh(tx)
        assert tx.category == "Miscellaneous"


def test_rerun_changes_nothing(session):
    _tx(session, "Transfer")
    clear_transfer_categories(session)
    assert clear_transfer_categories(session) == 0
