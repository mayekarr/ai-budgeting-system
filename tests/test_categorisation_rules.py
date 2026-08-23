from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Base, CategorisationRule
from categorisation.rules import match_rule


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s


def _add_rule(session, **overrides):
    defaults = dict(pattern="WOOLWORTHS", match_type="substring", category="Groceries",
                     subcategory=None, priority=100, source="seeded", is_active=True)
    defaults.update(overrides)
    session.add(CategorisationRule(**defaults))
    session.commit()


def test_exact_match_wins_over_substring(session):
    _add_rule(session, pattern="MYKI PAYMENTS MELBOURNE", match_type="exact",
              category="Transport", subcategory="Public Transport", priority=1)
    _add_rule(session, pattern="MYKI", match_type="substring", category="Miscellaneous", priority=50)

    result = match_rule(session, "MYKI PAYMENTS MELBOURNE")
    assert result is not None
    assert result.category == "Transport"
    assert result.subcategory == "Public Transport"
    assert result.confidence == 1.0


def test_substring_match(session):
    _add_rule(session, pattern="WOOLWORTHS", match_type="substring", category="Groceries")

    result = match_rule(session, "WOOLWORTHS/GLEBE ST & LOOFOREST HILL 036")
    assert result is not None
    assert result.category == "Groceries"


def test_regex_match(session):
    _add_rule(session, pattern=r"CREDIT CARD PAYMENT|DIRECT DEBIT PAYMENT", match_type="regex",
              category="Loans & Finance", subcategory="Loan Repayment")

    result = match_rule(session, "DIRECT DEBIT PAYMENT")
    assert result is not None
    assert result.category == "Loans & Finance"


def test_no_match_returns_none(session):
    _add_rule(session, pattern="WOOLWORTHS", match_type="substring", category="Groceries")

    assert match_rule(session, "SOME COMPLETELY UNKNOWN MERCHANT XYZ") is None


def test_inactive_rule_is_ignored(session):
    _add_rule(session, pattern="WOOLWORTHS", match_type="substring", category="Groceries", is_active=False)

    assert match_rule(session, "WOOLWORTHS 3345") is None


def test_priority_breaks_ties_within_same_match_type(session):
    _add_rule(session, pattern="HILLS", match_type="substring", category="Miscellaneous", priority=50)
    _add_rule(session, pattern="HILLS MEATS", match_type="substring", category="Groceries", priority=1)

    result = match_rule(session, "HILLS MEATS PTY LTDHILLS Forest Hill 036")
    assert result.category == "Groceries"
