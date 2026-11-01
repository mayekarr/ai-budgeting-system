from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.api as api_module
from backend.models import Account, Base, Transaction, TransferGroup


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "test_finance.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(bind=engine)
    monkeypatch.setattr(api_module, "engine", engine)
    monkeypatch.setattr(api_module, "SessionLocal", TestSessionLocal)
    Base.metadata.create_all(bind=engine)

    with TestSessionLocal() as s:
        jc = Account(name="JC", account_type="Everyday")
        ac = Account(name="AC", account_type="Everyday")
        cc = Account(name="CC", account_type="Credit Card")
        s.add_all([jc, ac, cc])
        s.flush()

        def tx(account, d, amount, desc, **kw):
            row = Transaction(account_id=account.id, date=d, amount=amount, raw_description=desc,
                              type=kw.pop("type", "Transfer"), **kw)
            s.add(row)
            s.flush()
            return row

        # A confident pair (Tier 1, 1.0), oldest.
        g1 = TransferGroup(detection_tier=1, confidence=1.0)
        # A tentative pair (Tier 2 medium, 0.6), newest.
        g2 = TransferGroup(detection_tier=2, confidence=0.6)
        s.add_all([g1, g2])
        s.flush()
        tx(jc, date(2026, 6, 1), -1000.0, "JC to AC", transfer_group_id=g1.id)
        tx(ac, date(2026, 6, 1), 1000.0, "AC from JC", transfer_group_id=g1.id)
        tx(ac, date(2026, 8, 10), -100.0, "LOOKS LIKE A TRANSFER", transfer_group_id=g2.id)
        tx(cc, date(2026, 8, 11), 99.5, "UBER TRIP", transfer_group_id=g2.id)
        # A lone transfer (counterpart not imported): a card payment on the card account.
        tx(cc, date(2026, 7, 5), 500.0, "DIRECT DEBIT PAYMENT")
        # Never listed: a superseded transfer and an ordinary expense.
        tx(cc, date(2026, 7, 6), 7.0, "PENDING", superseded_by_id=1)
        tx(jc, date(2026, 7, 7), -20.0, "COFFEE", type="Expense")
        s.commit()
        ids = {"jc": jc.id, "ac": ac.id, "cc": cc.id, "g1": g1.id, "g2": g2.id}

    return TestClient(api_module.app), TestSessionLocal, ids


def test_transfers_lists_pairs_newest_first_with_confidence_and_account_names(env):
    client, _, ids = env
    body = client.get("/transfers").json()

    assert [p["group_id"] for p in body["pairs"]] == [ids["g2"], ids["g1"]]
    tentative, confident = body["pairs"]
    assert (tentative["detection_tier"], tentative["confidence"]) == (2, 0.6)
    assert (confident["detection_tier"], confident["confidence"]) == (1, 1.0)
    assert confident["date"] == "2026-06-01" and confident["amount"] == 1000.0
    legs = confident["legs"]
    assert [(l["account_name"], l["amount"]) for l in legs] == [("JC", -1000.0), ("AC", 1000.0)]  # out first, in last
    assert {"id", "account_id", "date", "raw_description"} <= set(legs[0])


def test_transfers_lone_rows_are_separate_and_exclude_superseded_and_non_transfers(env):
    client, _, _ = env
    body = client.get("/transfers").json()
    assert [(l["raw_description"], l["account_name"]) for l in body["lone"]] == [("DIRECT DEBIT PAYMENT", "CC")]
    listed = {l["raw_description"] for p in body["pairs"] for l in p["legs"]} | {l["raw_description"] for l in body["lone"]}
    assert "PENDING" not in listed and "COFFEE" not in listed


def test_transfers_date_filter_keeps_a_pair_when_any_leg_is_in_range(env):
    client, _, ids = env
    body = client.get("/transfers", params={"date_from": "2026-08-11", "date_to": "2026-08-31"}).json()
    # The tentative pair has legs on the 10th and 11th; the 11th is in range, so the pair stays.
    assert [p["group_id"] for p in body["pairs"]] == [ids["g2"]]
    assert body["lone"] == []


def test_transfers_account_filter_keeps_pairs_touching_the_account_with_all_their_legs(env):
    client, _, ids = env
    body = client.get("/transfers", params={"account_id": ids["cc"]}).json()
    assert [p["group_id"] for p in body["pairs"]] == [ids["g2"]]
    assert len(body["pairs"][0]["legs"]) == 2          # the other leg is still shown
    assert [l["raw_description"] for l in body["lone"]] == ["DIRECT DEBIT PAYMENT"]
    other = client.get("/transfers", params={"account_id": ids["jc"]}).json()
    assert [p["group_id"] for p in other["pairs"]] == [ids["g1"]] and other["lone"] == []


def test_transfers_with_nothing_matching_is_empty_not_an_error(env):
    client, _, _ = env
    body = client.get("/transfers", params={"date_from": "2030-01-01"}).json()
    assert body == {"pairs": [], "lone": []}


def test_accounts_lists_every_account_by_id_and_name(env):
    client, _, ids = env
    body = client.get("/accounts").json()
    assert {(a["id"], a["name"]) for a in body} == {(ids["jc"], "JC"), (ids["ac"], "AC"), (ids["cc"], "CC")}
