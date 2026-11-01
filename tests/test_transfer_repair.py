from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Account, Base, CategorisationRule, Transaction, TransferGroup
from transfers.repair import rebuild_transfer_groups


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        s.add_all([Account(name="JC"), Account(name="AC"), Account(name="CC")])
        s.commit()
        yield s


def _acct(session, name):
    return session.query(Account).filter_by(name=name).one()


def _tx(session, account, d, amount, desc, bank_type, group=None, **kw):
    tx = Transaction(account_id=account.id, date=d, amount=amount, raw_description=desc,
                     raw_transaction_type=bank_type, type="Transfer" if group else kw.pop("type", "Expense"),
                     transfer_group=group, category=kw.pop("category", None), **kw)
    session.add(tx)
    session.flush()
    return tx


def _group(session, tier, confidence):
    g = TransferGroup(detection_tier=tier, confidence=confidence)
    session.add(g)
    session.flush()
    return g


@pytest.fixture()
def world(session):
    jc, ac, cc = _acct(session, "JC"), _acct(session, "AC"), _acct(session, "CC")
    d = date(2026, 3, 3)
    # 1. a confident Tier-1 pair: must be left exactly as it is
    g1 = _group(session, 1, 1.0)
    keep_a = _tx(session, jc, d, -500.0, "ONLINE Q1111111111 JC to AC", "TRANSFER DEBIT", g1)
    keep_b = _tx(session, ac, d, 500.0, "ONLINE Q1111111111 JC to AC", "TRANSFER CREDIT", g1)
    # 2. a real transfer with a card purchase wrongly attached (3 legs, Tier 2)
    g2 = _group(session, 2, 1.0)
    real_out = _tx(session, jc, d, -30.0, "ONLINE G1459687961 JC to AC", "TRANSFER DEBIT", g2)
    real_in = _tx(session, ac, d, 30.0, "ONLINE G1459687961 JC to AC", "TRANSFER CREDIT", g2)
    intruder = _tx(session, cc, d, -30.0, "Mater Lotteries Brisbane", "CREDIT CARD PURCHASE", g2)
    # 3. a near-equal pair that the old tolerance matching produced
    g3 = _group(session, 2, 0.6)
    near_a = _tx(session, ac, d, -100.0, "SHOP A", "TRANSFER DEBIT", g3)
    near_b = _tx(session, cc, d, 101.5, "SHOP B", "CREDIT CARD PAYMENT", g3)
    # 4. a genuine exact card payment matched by amount and date (Tier 2 high): must be rebuilt as a pair
    g4 = _group(session, 2, 1.0)
    pay_out = _tx(session, jc, d, -8050.2, "NAB CARD AUTOPAY", "AUTOMATIC DRAWING", g4)
    pay_in = _tx(session, cc, d, 8050.2, "DIRECT DEBIT PAYMENT", "CREDIT CARD PAYMENT", g4)
    session.commit()
    return dict(keep=(keep_a, keep_b), g1=g1, real=(real_out, real_in), intruder=intruder,
                near=(near_a, near_b), pay=(pay_out, pay_in))


def test_tier1_groups_are_left_alone(session, world):
    rebuild_transfer_groups(session)
    a, b = world["keep"]
    assert a.transfer_group_id == b.transfer_group_id == world["g1"].id and a.type == "Transfer"


def test_a_stray_row_is_freed_and_the_real_pair_is_rebuilt_on_its_reference(session, world):
    rebuild_transfer_groups(session)
    out, inn = world["real"]
    intruder = world["intruder"]
    assert out.transfer_group_id == inn.transfer_group_id is not None
    assert session.get(TransferGroup, out.transfer_group_id).detection_tier == 1
    assert intruder.transfer_group_id is None and intruder.type == "Expense"


def test_near_equal_pairs_are_dissolved_and_the_rows_go_back_to_income_and_expense(session, world):
    rebuild_transfer_groups(session)
    a, b = world["near"]
    assert a.transfer_group_id is None and b.transfer_group_id is None
    assert (a.type, b.type) == ("Expense", "Income")
    # Nothing places them, so they go back to the review queue like any unplaced row.
    assert a.needs_review is True and a.needs_review_reason == "llm_unavailable"


def test_a_genuine_exact_pair_is_matched_again(session, world):
    result = rebuild_transfer_groups(session)
    out, inn = world["pay"]
    assert out.transfer_group_id == inn.transfer_group_id is not None and out.type == "Transfer"
    assert result["dissolved_groups"] == 3


def test_categories_are_restored_for_freed_rows_from_a_backup(session, world):
    intruder = world["intruder"]
    rebuild_transfer_groups(session, restore_categories={intruder.id: ("Gifts & Donations", "Donations")})
    assert (intruder.category, intruder.subcategory) == ("Gifts & Donations", "Donations")


def test_without_a_backup_a_freed_row_is_recategorised_by_the_rules_or_left_unplaced(session, world):
    session.add(CategorisationRule(pattern="MATER LOTTERIES", match_type="substring", category="Gifts & Donations",
                                   subcategory="Donations", priority=100, source="seeded", is_active=True))
    session.commit()
    rebuild_transfer_groups(session)
    assert world["intruder"].category == "Gifts & Donations"
    near_a, _ = world["near"]
    assert near_a.category == "Miscellaneous"           # no rule matches: left as the unplaced default


def test_a_second_run_changes_nothing(session, world):
    rebuild_transfer_groups(session)
    again = rebuild_transfer_groups(session)
    assert again["dissolved_groups"] == 1 or again["dissolved_groups"] == 0   # only the rebuilt Tier-2 pair
    out, inn = world["real"]
    assert out.transfer_group_id == inn.transfer_group_id


# --- relinking rows that lost their pair (e.g. a whole group unlinked by one click) ---------------

from transfers.repair import relink_by_reference


def test_relink_pairs_unlinked_rows_that_share_a_reference_and_an_exact_amount(session):
    jc, ac = _acct(session, "JC"), _acct(session, "AC")
    d = date(2026, 5, 11)
    out = _tx(session, jc, d, -30.0, "ONLINE N6414309103 Arvan food MAYEKAR A", "TRANSFER DEBIT")
    inn = _tx(session, ac, d, 30.0, "ONLINE N6414309103 Arvan food MAYEKAR A", "TRANSFER CREDIT", type="Income")
    session.commit()

    assert relink_by_reference(session) == 2
    assert out.transfer_group_id == inn.transfer_group_id is not None
    assert session.get(TransferGroup, out.transfer_group_id).detection_tier == 1


def test_relink_never_pairs_on_amount_alone_or_across_a_purchase_or_a_near_miss(session):
    jc, ac, cc = _acct(session, "JC"), _acct(session, "AC"), _acct(session, "CC")
    d = date(2026, 5, 11)
    amount_only_a = _tx(session, jc, d, -100.0, "SOMETHING OUT", "TRANSFER DEBIT")
    amount_only_b = _tx(session, ac, d, 100.0, "SOMETHING IN", "TRANSFER CREDIT", type="Income")
    near_a = _tx(session, jc, d, -20.0, "ONLINE Q2222222222 gift", "TRANSFER DEBIT")
    near_b = _tx(session, ac, d, 20.5, "ONLINE Q2222222222 gift", "TRANSFER CREDIT", type="Income")
    purchase = _tx(session, cc, d, -30.0, "ONLINE N6414309103 NANDOS", "CREDIT CARD PURCHASE")
    session.commit()

    assert relink_by_reference(session) == 0
    for tx in (amount_only_a, amount_only_b, near_a, near_b, purchase):
        assert tx.transfer_group_id is None


def test_relink_is_idempotent(session):
    jc, ac = _acct(session, "JC"), _acct(session, "AC")
    _tx(session, jc, date(2026, 5, 11), -30.0, "ONLINE N6414309103 Arvan food", "TRANSFER DEBIT")
    _tx(session, ac, date(2026, 5, 11), 30.0, "ONLINE N6414309103 Arvan food", "TRANSFER CREDIT", type="Income")
    session.commit()
    relink_by_reference(session)
    assert relink_by_reference(session) == 0


def test_a_freed_rent_credit_is_never_re_paired_as_a_transfer(session):
    jc, ac = _acct(session, "JC"), _acct(session, "AC")
    d = date(2026, 3, 3)
    g = _group(session, 2, 1.0)
    rent = _tx(session, jc, d, 100.0, "ONLINE Q3333333333 rent", "TRANSFER CREDIT", g)
    debit = _tx(session, ac, d, -100.0, "ONLINE Q3333333333 rent", "TRANSFER DEBIT", g)
    rent.category, rent.subcategory = "Income", "Rental Income"
    session.commit()

    rebuild_transfer_groups(session)

    assert rent.transfer_group_id is None and rent.type == "Income"
    assert (rent.category, rent.subcategory) == ("Income", "Rental Income")
    assert debit.transfer_group_id is None


def test_the_report_counts_only_the_rows_it_freed(session, world):
    # A lone card payment elsewhere in the database is typed Transfer by the same run, but it was never
    # freed, so it must not be subtracted from the freed rows.
    cc = _acct(session, "CC")
    session.add(Transaction(account_id=cc.id, date=date(2026, 3, 9), amount=99.0, raw_description="DIRECT DEBIT PAYMENT",
                            raw_transaction_type="CREDIT CARD PAYMENT", type="Income"))
    session.commit()

    result = rebuild_transfer_groups(session)

    assert result["freed_rows"] == 7
    assert result["now_ordinary_rows"] == 3          # the stray card purchase and the two near-equal rows
    assert result["relinked_rows"] == 4


def test_a_freed_row_has_its_refund_flag_reset(session, world):
    intruder = world["intruder"]
    intruder.is_refund = True
    session.commit()
    rebuild_transfer_groups(session)
    assert intruder.is_refund is False


from transfers.repair import missing_bank_category_share


def test_missing_bank_category_share_counts_only_imported_rows(session):
    jc = _acct(session, "JC")
    for i in range(4):
        session.add(Transaction(account_id=jc.id, date=date(2026, 1, 1 + i), amount=-1.0, raw_description=f"r{i}",
                                source="bank_import", raw_bank_category="Groceries" if i < 3 else None))
    session.add(Transaction(account_id=jc.id, date=date(2026, 1, 9), amount=-1.0, raw_description="manual",
                            source="manual"))
    session.commit()
    assert missing_bank_category_share(session) == 0.25
