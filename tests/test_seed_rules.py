from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Base, CategorisationRule
from categorisation.seed_rules import SEED_RULES, seed_rules_if_empty


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s


def test_seeds_rules_from_real_source1_data(session):
    inserted = seed_rules_if_empty(session)

    assert inserted == len(SEED_RULES)
    assert session.query(CategorisationRule).filter_by(source="seeded").count() == len(SEED_RULES)

    woolworths = session.query(CategorisationRule).filter_by(pattern="WOOLWORTHS").one()
    assert woolworths.category == "Groceries"


def test_seeding_is_idempotent(session):
    seed_rules_if_empty(session)
    second_call_inserted = seed_rules_if_empty(session)

    assert second_call_inserted == 0
    assert session.query(CategorisationRule).filter_by(source="seeded").count() == len(SEED_RULES)


def test_more_specific_pattern_outranks_generic_one(session):
    # UBER EATS should win over the generic UBER rule for an Uber Eats transaction.
    seed_rules_if_empty(session)

    uber_eats_rule = session.query(CategorisationRule).filter_by(pattern="UBER EATS").one()
    uber_rule = session.query(CategorisationRule).filter_by(pattern="UBER").one()
    assert uber_eats_rule.priority < uber_rule.priority
