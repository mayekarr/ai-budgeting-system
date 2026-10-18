from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from assets.attribution import attribute_asset, load_asset_lookups, reattribute_assets
from backend.models import Account, AccountAlias, Asset, AssetAlias, Base, Transaction


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def real_shape(session):
    """Mirrors the real JC account: a shared everyday account, with loans named in its descriptions."""
    jericho = Asset(name="Jericho Ct", type="Real Estate")
    shares = Asset(name="Share Portfolio", type="Shares")
    barkly = Asset(name="Barkly Street", type="Residence")
    session.add_all([jericho, shares, barkly])
    session.flush()
    session.add(AssetAlias(asset_id=jericho.id, pattern="6 JERICHO CT"))

    jc = Account(name="JC", account_type="Everyday")
    session.add(jc)
    session.flush()
    session.add(AccountAlias(account_id=jc.id, raw_identifier="147912573"))
    for number, asset in [("34-188-5257", jericho), ("34-189-2465", shares), ("703206283", barkly)]:
        loan = Account(name=f"{asset.name} loan", account_type="Loan", asset_id=asset.id)
        session.add(loan)
        session.flush()
        session.add(AccountAlias(account_id=loan.id, raw_identifier=number))
    session.commit()
    return {"jericho": jericho.id, "shares": shares.id, "barkly": barkly.id, "jc": jc.id}


@pytest.mark.parametrize(
    "description, expected",
    [
        ("INTEREST CHARGED FROM A/C 34-188-5257", "jericho"),
        ("INTEREST CHARGED FROM A/C 34-189-2465", "shares"),
        ("LOAN REPAYMENT TO A/C 703206283 MAYEKAR A", "barkly"),
        ("6 Jericho Ct Berwi The Apostoli Gro Anila Mayekar &", "jericho"),
        # The same Barkly loan, written with dashes in a redraw line (2026-10-18).
        ("REDRAW PROCEEDS FROM A/C 70-320-6283", "barkly"),
    ],
)
def test_real_jc_rows_are_tagged_to_the_right_asset(session, real_shape, description, expected):
    lookups = load_asset_lookups(session)
    assert attribute_asset(description, real_shape["jc"], lookups) == real_shape[expected]


@pytest.mark.parametrize(
    "description",
    ["P0006175750 OXFAM AUSTRALIA Anila Mayekar", "4530307001277128 NAB CARD AUTOPAY MRS ANILA ROHAN"],
)
def test_unrelated_rows_on_a_shared_account_get_no_asset(session, real_shape, description):
    lookups = load_asset_lookups(session)
    assert attribute_asset(description, real_shape["jc"], lookups) is None


def test_non_loan_account_alias_in_description_does_not_tag(session, real_shape):
    # JC's own number appearing in another account's transfer text must not pull in an asset,
    # even if JC were later linked to one — only loan accounts are matched by number.
    jc = session.get(Account, real_shape["jc"])
    jc.asset_id = real_shape["jericho"]
    other = Account(name="AC", account_type="Everyday")
    session.add(other)
    session.commit()

    lookups = load_asset_lookups(session)
    assert attribute_asset("ONLINE L1957359363 TRANSFER TO 147912573", other.id, lookups) is None


def test_own_account_link_tags_every_row_on_it(session, real_shape):
    loan = session.query(Account).filter_by(name="Jericho Ct loan").one()
    lookups = load_asset_lookups(session)
    assert attribute_asset("PRINCIPAL REPAYMENT", loan.id, lookups) == real_shape["jericho"]


def test_loan_number_wins_over_asset_alias(session, real_shape):
    lookups = load_asset_lookups(session)
    description = "6 JERICHO CT SHARE LOAN INTEREST 34-189-2465"
    assert attribute_asset(description, real_shape["jc"], lookups) == real_shape["shares"]


def test_asset_alias_wins_over_own_account_link(session, real_shape):
    loan = session.query(Account).filter_by(name="Barkly Street loan").one()
    lookups = load_asset_lookups(session)
    assert attribute_asset("6 JERICHO CT ADJUSTMENT", loan.id, lookups) == real_shape["jericho"]


def test_asset_alias_match_is_case_insensitive(session, real_shape):
    lookups = load_asset_lookups(session)
    assert attribute_asset("rent 6 jericho ct", real_shape["jc"], lookups) == real_shape["jericho"]


def test_no_assets_configured_tags_nothing(session):
    account = Account(name="JC")
    session.add(account)
    session.commit()
    lookups = load_asset_lookups(session)
    assert attribute_asset("INTEREST CHARGED FROM A/C 34-188-5257", account.id, lookups) is None


def test_reattribute_rederives_every_row_from_the_current_setup(session, real_shape):
    # Nothing sets an asset by hand, so every tag is derived -- re-deriving all rows (not just
    # untagged ones) is what keeps a relinked or unlinked loan from leaving stale tags behind.
    jc = real_shape["jc"]
    interest = Transaction(account_id=jc, date=date(2026, 7, 31), amount=-4877.79,
                           raw_description="INTEREST CHARGED FROM A/C 34-188-5257")
    oxfam = Transaction(account_id=jc, date=date(2026, 8, 10), amount=-50.0,
                        raw_description="P0006175750 OXFAM AUSTRALIA Anila Mayekar")
    stale = Transaction(account_id=jc, date=date(2026, 7, 31), amount=-3847.91,
                        raw_description="INTEREST CHARGED FROM A/C 34-189-2465",
                        asset_id=real_shape["barkly"])
    session.add_all([interest, oxfam, stale])
    session.commit()

    changed = reattribute_assets(session)
    session.commit()

    assert changed == 2
    assert interest.asset_id == real_shape["jericho"]
    assert oxfam.asset_id is None
    assert stale.asset_id == real_shape["shares"]


def test_reattribute_clears_tags_after_a_loan_is_unlinked(session, real_shape):
    jc = real_shape["jc"]
    interest = Transaction(account_id=jc, date=date(2026, 7, 31), amount=-4877.79,
                           raw_description="INTEREST CHARGED FROM A/C 34-188-5257")
    session.add(interest)
    session.commit()
    reattribute_assets(session)

    loan = session.query(Account).filter_by(name="Jericho Ct loan").one()
    loan.asset_id = None
    reattribute_assets(session)
    session.commit()

    assert interest.asset_id is None
