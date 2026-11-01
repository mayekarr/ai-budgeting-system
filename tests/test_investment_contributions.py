from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Account, Base, Transaction
from transfers.investment_contributions import is_investment_contribution, reclassify_investment_contributions


@pytest.mark.parametrize("description, amount", [
    ("30774608 0003 MLC MKIS Rohan & Anila Ma", -750.0),
    ("30774608 0097 mlc mkis rohan & anila ma", -750.0),
])
def test_periodic_contribution_to_the_share_portfolio_is_recognised(description, amount):
    assert is_investment_contribution(description, amount) is True


@pytest.mark.parametrize("description, amount", [
    # The 2022-04-19 sale payout: a credit, and worded CREDITS. It is real income.
    ("30774608 0097 MLC MKIS CREDITS Rohan & Anila Ma", 284903.24),
    ("30774608 0097 MLC MKIS CREDITS Rohan & Anila Ma", -10.0),
    ("30774608 0003 MLC MKIS Rohan & Anila Ma", 750.0),
    ("MLC LIMITED DOCKLANDS", -325.47),          # insurance premiums are ordinary spending
    ("BPAY MLC Super 5088723914", -10000.0),
])
def test_payouts_premiums_and_other_mlc_rows_are_not_contributions(description, amount):
    assert is_investment_contribution(description, amount) is False


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        s.add(Account(name="JC"))
        s.commit()
        yield s


def _tx(session, description, amount):
    tx = Transaction(account_id=session.query(Account).one().id, date=date(2022, 4, 6), amount=amount,
                     raw_description=description, type="Expense", category="Miscellaneous",
                     needs_review=True, needs_review_reason="llm_unavailable")
    session.add(tx)
    session.commit()
    return tx


def test_reclassify_types_contributions_as_transfer_and_leaves_the_payout_alone(session):
    contribution = _tx(session, "30774608 0003 MLC MKIS Rohan & Anila Ma", -750.0)
    payout = _tx(session, "30774608 0097 MLC MKIS CREDITS Rohan & Anila Ma", 284903.24)
    assert reclassify_investment_contributions(session) == 1
    session.refresh(contribution)
    session.refresh(payout)
    assert contribution.type == "Transfer" and contribution.category is None
    assert contribution.needs_review is False and contribution.transfer_group_id is None
    assert payout.type == "Expense" and payout.category == "Miscellaneous"


def test_reclassify_is_idempotent(session):
    _tx(session, "30774608 0003 MLC MKIS Rohan & Anila Ma", -750.0)
    reclassify_investment_contributions(session)
    assert reclassify_investment_contributions(session) == 0


@pytest.mark.parametrize("description", [
    "30774608 0003 MLC  MKIS Rohan & Anila Ma",     # doubled space in the export
    "30774608 0003 MLC\tMKIS Rohan & Anila Ma",
])
def test_spacing_variants_are_still_contributions(description):
    assert is_investment_contribution(description, -750.0) is True


@pytest.mark.parametrize("description", [
    "30774608 0097 MLC MKIS CREDIT Rohan & Anila Ma",     # CREDIT without the S
    "30774608 0097 MLC  MKIS  CREDITS Rohan & Anila Ma",
])
def test_credit_wording_variants_are_not_contributions(description):
    assert is_investment_contribution(description, -10.0) is False
