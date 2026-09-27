from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from assets.seed import load_config, seed_assets
from backend.models import Account, AccountAlias, Asset, AssetAlias, Base, Transaction

CONFIG = {
    "assets": [
        {"name": "Jericho Ct", "type": "Real Estate", "aliases": ["6 JERICHO CT"]},
        {"name": "Share Portfolio", "type": "Shares"},
    ],
    "loans": [
        {"number": "34-188-5257", "name": "Jericho Ct loan", "asset": "Jericho Ct"},
        {"number": "34-189-2465", "name": "Share loan", "asset": "Share Portfolio"},
    ],
}


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s


def test_seed_creates_assets_aliases_and_linked_loan_accounts(session):
    seed_assets(session, CONFIG)
    session.commit()

    assert {a.name: a.type for a in session.query(Asset)} == {
        "Jericho Ct": "Real Estate", "Share Portfolio": "Shares",
    }
    assert [a.pattern for a in session.query(AssetAlias)] == ["6 JERICHO CT"]
    loan = session.query(AccountAlias).filter_by(raw_identifier="34-188-5257").one().account
    assert loan.name == "Jericho Ct loan"
    assert loan.account_type == "Loan"
    assert loan.asset.name == "Jericho Ct"


def test_seed_is_idempotent(session):
    seed_assets(session, CONFIG)
    session.commit()
    seed_assets(session, CONFIG)
    session.commit()

    assert session.query(Asset).count() == 2
    assert session.query(AssetAlias).count() == 1
    assert session.query(Account).count() == 2
    assert session.query(AccountAlias).count() == 2


def test_seed_links_an_existing_account_found_by_loan_number(session):
    # e.g. a loan statement was uploaded first, auto-creating an unnamed account for its number.
    existing = Account(name="34-188-5257")
    session.add(existing)
    session.flush()
    session.add(AccountAlias(account_id=existing.id, raw_identifier="34-188-5257"))
    session.commit()

    seed_assets(session, CONFIG)
    session.commit()

    assert existing.account_type == "Loan"
    assert existing.name == "Jericho Ct loan"
    assert existing.asset.name == "Jericho Ct"
    assert session.query(Account).count() == 2  # the existing one plus the share loan


def test_seed_updates_changed_asset_fields(session):
    seed_assets(session, CONFIG)
    session.commit()
    changed = {"assets": [{"name": "Jericho Ct", "type": "Real Estate", "is_active": False, "notes": "sold"}]}
    seed_assets(session, changed)
    session.commit()

    jericho = session.query(Asset).filter_by(name="Jericho Ct").one()
    assert jericho.is_active is False
    assert jericho.notes == "sold"


def test_seed_tags_rows_uploaded_before_it_ran(session):
    jc = Account(name="JC")
    session.add(jc)
    session.flush()
    rent = Transaction(account_id=jc.id, date=date(2026, 8, 5), amount=2704.86,
                       raw_description="6 Jericho Ct Berwi The Apostoli Gro")
    interest = Transaction(account_id=jc.id, date=date(2026, 7, 31), amount=-3847.91,
                           raw_description="INTEREST CHARGED FROM A/C 34-189-2465")
    session.add_all([rent, interest])
    session.commit()

    result = seed_assets(session, CONFIG)
    session.commit()

    assert result["tagged"] == 2
    assert rent.asset.name == "Jericho Ct"
    assert interest.asset.name == "Share Portfolio"


def test_seed_rejects_a_loan_naming_an_unknown_asset(session):
    bad = {"loans": [{"number": "703206283", "name": "Home loan", "asset": "Nowhere"}]}
    with pytest.raises(ValueError, match="Nowhere"):
        seed_assets(session, bad)


def test_load_config_reads_json_file(tmp_path):
    path = tmp_path / "assets.local.json"
    path.write_text(json.dumps(CONFIG), encoding="utf-8")
    assert load_config(path) == CONFIG


def test_committed_example_config_is_valid(session):
    from pathlib import Path

    example = load_config(Path(__file__).resolve().parent.parent / "config" / "assets.example.json")
    seed_assets(session, example)
    assert session.query(Asset).count() == len(example["assets"])


def test_seed_moves_an_alias_that_changed_assets_in_the_config(session):
    seed_assets(session, CONFIG)
    session.commit()
    moved = {"assets": [{"name": "Share Portfolio", "type": "Shares", "aliases": ["6 JERICHO CT"]}]}
    seed_assets(session, moved)
    session.commit()

    alias = session.query(AssetAlias).filter_by(pattern="6 JERICHO CT").one()
    assert alias.asset.name == "Share Portfolio"


@pytest.mark.parametrize("pattern", ["", "  "])
def test_seed_rejects_a_blank_alias(session, pattern):
    with pytest.raises(ValueError, match="blank"):
        seed_assets(session, {"assets": [{"name": "X", "type": "Other", "aliases": [pattern]}]})
