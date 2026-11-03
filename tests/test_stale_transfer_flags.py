from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Account, Base, Transaction, TransferGroup
from backend.needs_review_reasons import LLM_UNAVAILABLE, LOW_CONFIDENCE_CATEGORY, TRANSFER_MATCH, UNRECOGNISED_ACCOUNT
from transfers.stale_flags import clear_stale_transfer_match_flags


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        s.add_all([Account(name="JC"), Account(name="AC")])
        s.commit()
        yield s


def _flagged(session, account_name="JC", **kw):
    account = session.query(Account).filter_by(name=account_name).one()
    fields = dict(account_id=account.id, date=date(2026, 3, 3), amount=-30.0, raw_description="WOOLWORTHS",
                  type="Expense", category="Groceries", confidence_score=1.0, needs_review=True,
                  needs_review_reason=TRANSFER_MATCH, raw_transaction_type="CREDIT CARD PURCHASE")
    fields.update(kw)
    tx = Transaction(**fields)
    session.add(tx)
    session.commit()
    return tx


def test_a_flag_with_no_pair_and_no_candidate_is_cleared(session):
    tx = _flagged(session)

    assert clear_stale_transfer_match_flags(session) == 1
    assert (tx.needs_review, tx.needs_review_reason) == (False, None)
    assert tx.category == "Groceries"


def test_a_row_still_waiting_on_a_category_goes_back_to_that_reason_instead_of_leaving_review(session):
    # The transfer flag had replaced "no category could be found"; dropping it would hide the row.
    tx = _flagged(session, category="Miscellaneous", confidence_score=0.0, type="Income", amount=100.0)

    assert clear_stale_transfer_match_flags(session) == 1
    assert (tx.needs_review, tx.needs_review_reason) == (True, LLM_UNAVAILABLE)


def test_a_tie_loser_beside_a_tentative_pair_keeps_its_flag(session):
    # A tied with C1 and C2: A paired with C1 (tentative, 0.6) and C2 was flagged. C2 has no ungrouped
    # candidate left (A is taken), but the flag is the only sign that the pairing was an arbitrary choice.
    jc = session.query(Account).filter_by(name="JC").one()
    ac = session.query(Account).filter_by(name="AC").one()
    group = TransferGroup(detection_tier=2, confidence=0.6)
    session.add(group)
    session.flush()
    session.add_all([
        Transaction(account_id=jc.id, date=date(2026, 3, 3), amount=-50.0, raw_description="a", type="Transfer",
                    transfer_group_id=group.id, raw_transaction_type="TRANSFER DEBIT"),
        Transaction(account_id=ac.id, date=date(2026, 3, 3), amount=50.0, raw_description="c1", type="Transfer",
                    transfer_group_id=group.id, raw_transaction_type="TRANSFER CREDIT"),
    ])
    session.commit()
    loser = _flagged(session, "AC", amount=50.0, type="Income", category="Income", raw_transaction_type="TRANSFER CREDIT",
                     raw_description="c2")

    assert clear_stale_transfer_match_flags(session) == 0
    assert loser.needs_review_reason == TRANSFER_MATCH


def test_a_row_the_llm_really_categorised_does_not_come_back_as_llm_unavailable(session):
    # Confidence 0.0 is what 'nothing could categorise this' leaves; a real answer of Miscellaneous at 0.9 is not that.
    tx = _flagged(session, category="Miscellaneous", confidence_score=0.9, type="Income", amount=100.0)

    assert clear_stale_transfer_match_flags(session) == 1
    assert (tx.needs_review, tx.needs_review_reason) == (True, LOW_CONFIDENCE_CATEGORY)


def test_an_ungrouped_transfer_row_with_a_stale_flag_is_cleared_too(session):
    tx = _flagged(session, type="Transfer", category=None, confidence_score=1.0, raw_transaction_type="CREDIT CARD PAYMENT")

    assert clear_stale_transfer_match_flags(session) == 1
    assert (tx.needs_review, tx.needs_review_reason) == (False, None)


def test_a_flag_with_a_current_candidate_is_kept(session):
    tx = _flagged(session, amount=-50.0, raw_transaction_type="TRANSFER DEBIT", raw_description="to a friend")
    ac = session.query(Account).filter_by(name="AC").one()
    session.add(Transaction(account_id=ac.id, date=date(2026, 3, 3), amount=50.0, raw_description="from a friend",
                            type="Income", raw_transaction_type="TRANSFER CREDIT"))
    session.commit()

    assert clear_stale_transfer_match_flags(session) == 0
    assert tx.needs_review_reason == TRANSFER_MATCH


def test_a_row_in_a_pair_is_left_alone(session):
    group = TransferGroup(detection_tier=2, confidence=0.6)
    session.add(group)
    session.flush()
    tx = _flagged(session, type="Transfer", transfer_group_id=group.id)

    assert clear_stale_transfer_match_flags(session) == 0
    assert tx.needs_review_reason == TRANSFER_MATCH


def test_other_review_reasons_are_untouched(session):
    tx = _flagged(session, needs_review_reason=UNRECOGNISED_ACCOUNT)

    assert clear_stale_transfer_match_flags(session) == 0
    assert tx.needs_review_reason == UNRECOGNISED_ACCOUNT


def test_a_second_run_changes_nothing(session):
    _flagged(session)
    _flagged(session, category="Miscellaneous", confidence_score=0.0, type="Income", amount=100.0)

    clear_stale_transfer_match_flags(session)

    assert clear_stale_transfer_match_flags(session) == 0
