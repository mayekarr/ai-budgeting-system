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


def _add_pair(Session, ids, tier, confidence, out_desc, in_desc, out_type="TRANSFER DEBIT", in_type="TRANSFER CREDIT"):
    with Session() as s:
        group = TransferGroup(detection_tier=tier, confidence=confidence)
        s.add(group)
        s.flush()
        s.add(Transaction(account_id=ids["jc"], date=date(2026, 9, 1), amount=-50.0, raw_description=out_desc,
                          type="Transfer", transfer_group_id=group.id, raw_transaction_type=out_type))
        s.add(Transaction(account_id=ids["ac"], date=date(2026, 9, 1), amount=50.0, raw_description=in_desc,
                          type="Transfer", transfer_group_id=group.id, raw_transaction_type=in_type))
        s.commit()
        return group.id


def _check_flags(client):
    return {p["group_id"]: p["needs_check"] for p in client.get("/transfers").json()["pairs"]}


def test_a_tier2_pair_whose_two_sides_share_no_wording_needs_checking(env):
    client, Session, ids = env
    wrong = _add_pair(Session, ids, 2, 1.0, "P0005826535 OXFAM AUSTRALIA Anila Ma", "MR AMARNANDAN PERIYA gift from a friend")
    assert _check_flags(client)[wrong] is True


def test_a_tier2_pair_with_the_same_wording_on_both_sides_does_not(env):
    client, Session, ids = env
    fine = _add_pair(Session, ids, 2, 1.0, "INTERNET TRANSFER Trans salary Anila", "INTERNET TRANSFER Trans salary Anila")
    jc_to_ac = _add_pair(Session, ids, 2, 1.0, "ROHAN MAYEKAR L6497124807 AC to RC", "MRS ANILA ROHAN MAYEAC to RC AC to R")
    flags = _check_flags(client)
    assert flags[fine] is False and flags[jc_to_ac] is False


def test_a_card_payment_pair_never_needs_checking_whatever_the_wording(env):
    client, Session, ids = env
    card = _add_pair(Session, ids, 2, 1.0, "4530307001277128 NAB CARD AUTOPAY MRS ANILA", "DIRECT DEBIT PAYMENT",
                     out_type="AUTOMATIC DRAWING", in_type="CREDIT CARD PAYMENT")
    assert _check_flags(client)[card] is False


def test_tier1_pairs_never_need_checking_and_tentative_pairs_always_do(env):
    client, _, ids = env
    flags = _check_flags(client)
    assert flags[ids["g1"]] is False     # Tier 1: matched on a reference or account number
    assert flags[ids["g2"]] is True      # Tier 2 at 60%: matched on amount and date alone


def test_a_monthly_direct_debit_is_not_mistaken_for_a_card_payment(env):
    # Oxfam is drawn monthly as an AUTOMATIC DRAWING, the same bank type as a card autopay. Only a
    # pair that includes the card's own CREDIT CARD PAYMENT leg is a card payment.
    client, Session, ids = env
    wrong = _add_pair(Session, ids, 2, 1.0, "P0005826535 OXFAM AUSTRALIA Anila Mayekar",
                      "MR AMARNANDAN PERIYAavdesh gift - amar", out_type="AUTOMATIC DRAWING", in_type="TRANSFER CREDIT")
    assert _check_flags(client)[wrong] is True


def test_a_group_with_only_one_live_leg_is_listed_as_a_lone_transfer_not_a_one_row_pair(env):
    client, Session, ids = env
    with Session() as s:
        group = TransferGroup(detection_tier=2, confidence=1.0)
        s.add(group)
        s.flush()
        s.add(Transaction(account_id=ids["jc"], date=date(2026, 9, 2), amount=-77.0, raw_description="LIVE LEG",
                          type="Transfer", transfer_group_id=group.id))
        s.add(Transaction(account_id=ids["ac"], date=date(2026, 9, 2), amount=77.0, raw_description="GONE LEG",
                          type="Transfer", transfer_group_id=group.id, superseded_by_id=1))
        s.commit()
        group_id = group.id

    body = client.get("/transfers").json()

    assert group_id not in {p["group_id"] for p in body["pairs"]}
    assert "LIVE LEG" in {l["raw_description"] for l in body["lone"]}


def test_a_pair_is_kept_only_when_one_leg_satisfies_both_the_account_and_date_filters(env):
    client, Session, ids = env
    with Session() as s:
        group = TransferGroup(detection_tier=1, confidence=1.0)
        s.add(group)
        s.flush()
        # Leg on JC in January, leg on AC in March.
        s.add(Transaction(account_id=ids["jc"], date=date(2026, 1, 5), amount=-61.0, raw_description="SPLIT OUT",
                          type="Transfer", transfer_group_id=group.id))
        s.add(Transaction(account_id=ids["ac"], date=date(2026, 3, 5), amount=61.0, raw_description="SPLIT IN",
                          type="Transfer", transfer_group_id=group.id))
        s.commit()
        group_id = group.id

    def groups(**params):
        return {p["group_id"] for p in client.get("/transfers", params=params).json()["pairs"]}

    # JC (January leg) with a March-only range: no single leg is on JC AND in March.
    assert group_id not in groups(account_id=ids["jc"], date_from="2026-03-01", date_to="2026-03-31")
    # JC with a range containing the January leg, and AC with March, both match one leg.
    assert group_id in groups(account_id=ids["jc"], date_from="2026-01-01", date_to="2026-01-31")
    assert group_id in groups(account_id=ids["ac"], date_from="2026-03-01", date_to="2026-03-31")
