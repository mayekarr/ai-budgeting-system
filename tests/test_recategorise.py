from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Account, Base, CategorisationRule, Transaction
from categorisation.recategorise import recategorise_unreviewed


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        s.add(Account(name="JC"))
        s.add(CategorisationRule(pattern="P & G REAL ESTAT", match_type="substring", category="Income",
                                 subcategory="Rental Income", priority=130, source="seeded", is_active=True))
        s.commit()
        yield s


def _tx(session, description, amount=1000.0, **kw):
    tx = Transaction(account_id=session.query(Account).one().id, date=date(2025, 1, 1), amount=amount,
                     raw_description=description, type=kw.pop("type", "Income"),
                     category=kw.pop("category", "Miscellaneous"),
                     needs_review=kw.pop("needs_review", True),
                     needs_review_reason=kw.pop("needs_review_reason", "llm_unavailable"), **kw)
    session.add(tx)
    session.commit()
    return tx


def test_unreviewed_row_that_now_matches_a_rule_is_categorised_and_cleared(session):
    tx = _tx(session, "6 Jericho Ct Berwi P & G Real Estat Anila")
    assert recategorise_unreviewed(session) == 1
    session.refresh(tx)
    assert (tx.category, tx.subcategory, tx.type) == ("Income", "Rental Income", "Income")
    assert tx.needs_review is False and tx.needs_review_reason is None and tx.confidence_score == 1.0


def test_rerun_changes_nothing(session):
    _tx(session, "6 Jericho Ct Berwi P & G Real Estat Anila")
    recategorise_unreviewed(session)
    assert recategorise_unreviewed(session) == 0


def test_row_without_a_matching_rule_is_left_alone(session):
    tx = _tx(session, "SOMETHING UNKNOWN")
    assert recategorise_unreviewed(session) == 0
    session.refresh(tx)
    assert tx.category == "Miscellaneous" and tx.needs_review is True


def test_transfers_and_rows_with_other_review_reasons_are_not_touched(session):
    transfer = _tx(session, "P & G REAL ESTAT", type="Transfer", needs_review=False, needs_review_reason=None)
    other = _tx(session, "P & G REAL ESTAT", needs_review_reason="unrecognised_account")
    assert recategorise_unreviewed(session) == 0
    session.refresh(transfer)
    session.refresh(other)
    assert transfer.category == "Miscellaneous" and other.category == "Miscellaneous"


def test_a_manually_corrected_row_is_not_overwritten(session):
    tx = _tx(session, "P & G REAL ESTAT", category="Insurance", needs_review=False, needs_review_reason=None)
    assert recategorise_unreviewed(session) == 0
    session.refresh(tx)
    assert tx.category == "Insurance"


def test_unconfident_miscellaneous_row_that_lost_its_review_flag_is_also_picked_up(session):
    # e.g. a row restored by "not a transfer", which clears the flag but keeps the old category
    tx = _tx(session, "P & G REAL ESTAT", needs_review=False, needs_review_reason=None, confidence_score=0.0)
    assert recategorise_unreviewed(session) == 1
    session.refresh(tx)
    assert tx.subcategory == "Rental Income"
