from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Account, AccountAlias, Base
from ingestion.account_resolution import resolve_account


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s


def test_resolves_known_alias_to_existing_account(session):
    account = Account(name="Rohan's Classic", institution="NAB", owner="Rohan", account_type="Everyday")
    session.add(account)
    session.flush()
    session.add(AccountAlias(account_id=account.id, raw_identifier="133500607"))
    session.commit()

    result = resolve_account(session, "133500607")

    assert result.account.id == account.id
    assert result.was_created is False


def test_dual_identifier_linkage_resolves_to_same_account():
    # §4.1: "Card ending 7128" and the masked full number "453030xxxxxx7128" are the same account.
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        account = Account(name="CC", institution="NAB", owner="Rohan", account_type="Credit Card")
        session.add(account)
        session.flush()
        session.add_all([
            AccountAlias(account_id=account.id, raw_identifier="Card ending 7128"),
            AccountAlias(account_id=account.id, raw_identifier="453030xxxxxx7128"),
        ])
        session.commit()

        r1 = resolve_account(session, "Card ending 7128")
        r2 = resolve_account(session, "453030xxxxxx7128")
        assert r1.account.id == r2.account.id


def test_unknown_identifier_auto_creates_account_and_flags_for_review(session):
    result = resolve_account(session, "999999999")

    assert result.was_created is True
    assert result.needs_review is True
    assert result.account.id is not None

    alias = session.query(AccountAlias).filter_by(raw_identifier="999999999").one()
    assert alias.account_id == result.account.id
