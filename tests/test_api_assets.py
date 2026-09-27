from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.api as api_module
from backend.models import Account, AccountAlias, Asset, Base, Transaction


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "test_finance.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(bind=engine)
    monkeypatch.setattr(api_module, "engine", engine)
    monkeypatch.setattr(api_module, "SessionLocal", TestSessionLocal)
    Base.metadata.create_all(bind=engine)

    with TestSessionLocal() as s:
        jericho = Asset(name="Jericho Ct", type="Real Estate")
        shares = Asset(name="Share Portfolio", type="Shares")
        s.add_all([jericho, shares])
        jc = Account(name="JC", account_type="Everyday")
        s.add(jc)
        s.flush()

        def tx(d, amount, desc, asset, **kw):
            s.add(Transaction(account_id=jc.id, date=d, amount=amount, raw_description=desc,
                              asset_id=asset.id if asset else None, **kw))

        tx(date(2026, 7, 31), -4877.79, "INTEREST CHARGED FROM A/C 34-188-5257", jericho,
           category="Loans & Finance", subcategory="Loan Interest")
        tx(date(2026, 8, 5), 2704.86, "6 Jericho Ct rent", jericho,
           category="Income", subcategory="Rental Income", type="Income")
        tx(date(2026, 7, 31), -3847.91, "INTEREST CHARGED FROM A/C 34-189-2465", shares,
           category="Loans & Finance", subcategory="Loan Interest")
        # Excluded from rollups/drill-in, same as GET /summary: a transfer, and a superseded pending row.
        tx(date(2026, 8, 1), -1000.00, "TRANSFER TO JERICHO LOAN", jericho, type="Transfer")
        tx(date(2026, 8, 2), -99.00, "PENDING", jericho, category="Housing", superseded_by_id=1)
        # Untagged row never shows up under any asset.
        tx(date(2026, 8, 10), -50.00, "OXFAM", None, category="Gifts & Donations")
        s.commit()
        ids = {"jericho": jericho.id, "shares": shares.id, "jc": jc.id}

    return TestClient(api_module.app), TestSessionLocal, ids


def _by_name(body):
    return {a["name"]: a for a in body["assets"]}


def test_get_assets_rolls_up_income_expense_net_per_asset(env):
    client, _, _ = env
    body = client.get("/assets").json()
    assets = _by_name(body)

    assert assets["Jericho Ct"]["income"] == pytest.approx(2704.86)
    assert assets["Jericho Ct"]["expense"] == pytest.approx(4877.79)
    assert assets["Jericho Ct"]["net"] == pytest.approx(2704.86 - 4877.79)
    assert assets["Jericho Ct"]["type"] == "Real Estate"
    assert assets["Share Portfolio"]["expense"] == pytest.approx(3847.91)
    assert body["total"]["income"] == pytest.approx(2704.86)
    assert body["total"]["expense"] == pytest.approx(4877.79 + 3847.91)
    assert body["total"]["net"] == pytest.approx(2704.86 - 4877.79 - 3847.91)


def test_get_assets_respects_date_range(env):
    client, _, _ = env
    assets = _by_name(client.get("/assets", params={"date_from": "2026-08-01"}).json())
    assert assets["Jericho Ct"]["expense"] == pytest.approx(0.0)
    assert assets["Jericho Ct"]["income"] == pytest.approx(2704.86)
    assert assets["Share Portfolio"]["net"] == pytest.approx(0.0)


def test_get_assets_lists_an_asset_with_no_transactions(env):
    client, _, _ = env
    client.post("/assets", json={"name": "Barkly Street", "type": "Residence"})
    assets = _by_name(client.get("/assets").json())
    assert assets["Barkly Street"]["net"] == 0.0
    assert assets["Barkly Street"]["is_active"] is True


def test_asset_transactions_drill_in_excludes_transfers_and_superseded(env):
    client, _, ids = env
    rows = client.get(f"/assets/{ids['jericho']}/transactions").json()
    assert sorted(r["raw_description"] for r in rows) == [
        "6 Jericho Ct rent", "INTEREST CHARGED FROM A/C 34-188-5257",
    ]
    assert all(r["asset_id"] == ids["jericho"] for r in rows)


def test_asset_transactions_drill_in_respects_date_range(env):
    client, _, ids = env
    rows = client.get(f"/assets/{ids['jericho']}/transactions", params={"date_to": "2026-07-31"}).json()
    assert [r["raw_description"] for r in rows] == ["INTEREST CHARGED FROM A/C 34-188-5257"]


def test_asset_transactions_unknown_asset_is_404(env):
    client, _, _ = env
    assert client.get("/assets/999/transactions").status_code == 404


def test_post_asset_creates_it_with_aliases_and_tags_existing_rows(env):
    client, Session, ids = env
    response = client.post("/assets", json={"name": "Charity", "type": "Other", "aliases": ["OXFAM"]})
    assert response.status_code == 201
    created = response.json()
    assert created["name"] == "Charity"

    with Session() as s:
        oxfam = s.query(Transaction).filter_by(raw_description="OXFAM").one()
        assert oxfam.asset_id == created["id"]


def test_post_asset_duplicate_name_is_409(env):
    client, _, _ = env
    assert client.post("/assets", json={"name": "Jericho Ct", "type": "Real Estate"}).status_code == 409


def test_patch_account_links_loan_to_asset_and_tags_existing_rows(env):
    client, Session, ids = env
    with Session() as s:
        loan = Account(name="34-188-5257")
        s.add(loan)
        s.flush()
        s.add(AccountAlias(account_id=loan.id, raw_identifier="34-188-5257"))
        # An untagged interest line already uploaded before the loan was linked.
        s.add(Transaction(account_id=ids["jc"], date=date(2026, 6, 30), amount=-4800.0,
                          raw_description="INTEREST CHARGED FROM A/C 34-188-5257 JUNE"))
        s.commit()
        loan_id = loan.id

    response = client.patch(
        f"/accounts/{loan_id}",
        json={"name": "Jericho Ct loan", "account_type": "Loan", "asset_id": ids["jericho"]},
    )
    assert response.status_code == 200
    assert response.json()["asset_id"] == ids["jericho"]
    assert response.json()["account_type"] == "Loan"

    with Session() as s:
        june = s.query(Transaction).filter_by(raw_description="INTEREST CHARGED FROM A/C 34-188-5257 JUNE").one()
        assert june.asset_id == ids["jericho"]


def test_patch_account_unknown_account_is_404(env):
    client, _, _ = env
    assert client.patch("/accounts/999", json={"name": "x"}).status_code == 404


def test_patch_account_unknown_asset_is_400(env):
    client, _, ids = env
    assert client.patch(f"/accounts/{ids['jc']}", json={"asset_id": 999}).status_code == 400


def test_patch_account_rejects_unknown_fields(env):
    client, _, ids = env
    assert client.patch(f"/accounts/{ids['jc']}", json={"owner_typo": "x"}).status_code == 422


@pytest.mark.parametrize("alias", ["", "   "])
def test_post_asset_rejects_blank_alias(env, alias):
    # A blank pattern is a substring of every description, so it would tag every transaction.
    client, Session, _ = env
    response = client.post("/assets", json={"name": "Everything", "type": "Other", "aliases": [alias]})
    assert response.status_code == 400
    with Session() as s:
        assert s.query(Asset).filter_by(name="Everything").one_or_none() is None
        assert s.query(Transaction).filter_by(raw_description="OXFAM").one().asset_id is None


def test_post_asset_duplicate_alias_is_409(env):
    client, _, _ = env
    assert client.post("/assets", json={"name": "A", "type": "Other", "aliases": ["OXFAM"]}).status_code == 201
    assert client.post("/assets", json={"name": "B", "type": "Other", "aliases": ["oxfam"]}).status_code == 409


def test_patch_account_null_name_is_rejected(env):
    client, _, ids = env
    assert client.patch(f"/accounts/{ids['jc']}", json={"name": None}).status_code == 422


def test_patch_account_relinking_moves_existing_tags(env):
    client, Session, ids = env
    with Session() as s:
        loan = Account(name="Loan", account_type="Loan", asset_id=ids["jericho"])
        s.add(loan)
        s.flush()
        s.add(AccountAlias(account_id=loan.id, raw_identifier="99-999-9999"))
        s.add(Transaction(account_id=ids["jc"], date=date(2026, 7, 1), amount=-10.0,
                          raw_description="INTEREST CHARGED FROM A/C 99-999-9999", asset_id=ids["jericho"]))
        s.commit()
        loan_id = loan.id

    assert client.patch(f"/accounts/{loan_id}", json={"asset_id": ids["shares"]}).status_code == 200
    with Session() as s:
        row = s.query(Transaction).filter_by(raw_description="INTEREST CHARGED FROM A/C 99-999-9999").one()
        assert row.asset_id == ids["shares"]

    assert client.patch(f"/accounts/{loan_id}", json={"asset_id": None}).status_code == 200
    with Session() as s:
        row = s.query(Transaction).filter_by(raw_description="INTEREST CHARGED FROM A/C 99-999-9999").one()
        assert row.asset_id is None
