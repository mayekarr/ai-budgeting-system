from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Account, Base, Transaction, TransferGroup
from categorisation.capital_events import (
    LOAN_DRAWDOWN,
    LOAN_PAYDOWN,
    SHARE_CONTRIBUTION,
    classify_capital_event,
    is_capital_event,
    reclassify_capital_events,
)
from categorisation.taxonomy import is_valid_category


@pytest.mark.parametrize("tag", [LOAN_DRAWDOWN, LOAN_PAYDOWN, SHARE_CONTRIBUTION])
def test_every_tag_is_a_valid_taxonomy_pair(tag):
    assert is_valid_category(tag.category, tag.subcategory)


def test_new_subcategories_exist():
    assert is_valid_category("Investment", "Super Contribution")
    assert is_valid_category("Investment", "Share Portfolio Contribution")


@pytest.mark.parametrize("description, amount, tag", [
    ("LOAN PROCEEDS FROM A/C 34-188-5257", 900000.0, LOAN_DRAWDOWN),
    ("REDRAW PROCEEDS FROM A/C 70-320-6283", 47000.0, LOAN_DRAWDOWN),
    ("ONLINE N8131366871 JC to Barkly HL MAYEKAR A", -582076.0, LOAN_PAYDOWN),
    ("30774608 0003 MLC MKIS Rohan & Anila Ma", -750.0, SHARE_CONTRIBUTION),
])
def test_classify_recognises_each_capital_event(description, amount, tag):
    assert classify_capital_event(description, amount) == tag


@pytest.mark.parametrize("description, amount", [
    ("LOAN INSTALMENT TO A/C 399934242 MAYEKAR", -244.89),         # regular instalments stay ordinary
    ("30774608 0097 MLC MKIS CREDITS Rohan & Anila Ma", 284903.24),  # the sale payout is a different tag
    ("WOOLWORTHS", -12.0),
])
def test_classify_ignores_everything_else(description, amount):
    assert classify_capital_event(description, amount) is None


@pytest.mark.parametrize("category, subcategory, expected", [
    ("Income", "Property Sale Proceeds", True),
    ("Income", "Investment Sale Proceeds", True),
    ("Income", "Loan Drawdown", True),
    ("Income", "Salary", False),
    ("Income", "Rental Income", False),
    ("Investment", "Property Purchase", True),
    ("Investment", None, True),
    ("Loans & Finance", "Loan Paydown", True),
    ("Loans & Finance", "Loan Repayment", False),
    ("Groceries", None, False),
    (None, None, False),
])
def test_is_capital_event(category, subcategory, expected):
    assert is_capital_event(category, subcategory) is expected


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        s.add(Account(name="JC"))
        s.commit()
        yield s


def _tx(session, description, amount, **kw):
    tx = Transaction(account_id=session.query(Account).one().id, date=date(2025, 9, 8), amount=amount,
                     raw_description=description, type=kw.pop("type", "Transfer"),
                     category=kw.pop("category", None),
                     needs_review=kw.pop("needs_review", False),
                     needs_review_reason=kw.pop("needs_review_reason", None), **kw)
    session.add(tx)
    session.commit()
    return tx


def test_reclassify_moves_a_groupless_transfer_to_its_capital_tag(session):
    drawdown = _tx(session, "LOAN PROCEEDS FROM A/C 34-188-5257", 900000.0)
    paydown = _tx(session, "ONLINE N8131366871 JC to Barkly HL MAYEKAR A", -582076.0)
    contribution = _tx(session, "30774608 0003 MLC MKIS Rohan & Anila Ma", -750.0)

    assert reclassify_capital_events(session) == 3

    assert (drawdown.type, drawdown.category, drawdown.subcategory) == ("Income", "Income", "Loan Drawdown")
    assert (paydown.type, paydown.category, paydown.subcategory) == ("Expense", "Loans & Finance", "Loan Paydown")
    assert (contribution.type, contribution.category, contribution.subcategory) == (
        "Expense", "Investment", "Share Portfolio Contribution")
    assert all(tx.confidence_score == 1.0 and tx.is_refund is False for tx in (drawdown, paydown, contribution))


def test_reclassify_also_fixes_a_row_still_typed_by_sign_with_a_review_flag(session):
    tx = _tx(session, "LOAN PROCEEDS FROM A/C 34-188-5257", 5.0, type="Income", category="Miscellaneous",
             needs_review=True, needs_review_reason="llm_unavailable")
    assert reclassify_capital_events(session) == 1
    assert tx.subcategory == "Loan Drawdown" and tx.needs_review is False and tx.needs_review_reason is None


def test_reclassify_keeps_an_unrecognised_account_flag(session):
    tx = _tx(session, "LOAN PROCEEDS FROM A/C 34-188-5257", 5.0, needs_review=True,
             needs_review_reason="unrecognised_account")
    reclassify_capital_events(session)
    assert tx.needs_review is True and tx.needs_review_reason == "unrecognised_account"


def test_reclassify_is_idempotent(session):
    _tx(session, "LOAN PROCEEDS FROM A/C 34-188-5257", 900000.0)
    assert reclassify_capital_events(session) == 1
    assert reclassify_capital_events(session) == 0


def test_reclassify_leaves_grouped_and_superseded_rows_alone(session):
    group = TransferGroup(detection_tier=1)
    session.add(group)
    session.commit()
    grouped = _tx(session, "ONLINE X JC to Barkly HL MAYEKAR A", -100.0, transfer_group_id=group.id)
    settled = _tx(session, "ONLINE X JC to Barkly HL MAYEKAR A", -100.0, type="Expense", category="Miscellaneous")
    pending = _tx(session, "ONLINE X JC to Barkly HL MAYEKAR A", -100.0, type="Expense",
                  category="Miscellaneous", superseded_by_id=settled.id)

    assert reclassify_capital_events(session) == 1  # only the settled, ungrouped row
    assert grouped.type == "Transfer" and pending.category == "Miscellaneous"
    assert settled.subcategory == "Loan Paydown"


def test_sql_clause_agrees_with_the_python_predicate(session):
    from categorisation.capital_events import capital_event_clause

    pairs = [("Income", "Loan Drawdown"), ("Income", "Salary"), ("Investment", "Property Purchase"),
             ("Loans & Finance", "Loan Paydown"), ("Loans & Finance", "Loan Repayment"), (None, None),
             ("Groceries", None)]
    for i, (category, subcategory) in enumerate(pairs):
        session.add(Transaction(account_id=session.query(Account).one().id, date=date(2026, 1, 1), amount=-1.0,
                                raw_description=f"row {i}", type="Expense", category=category,
                                subcategory=subcategory))
    session.commit()
    in_clause = {t.raw_description for t in session.query(Transaction).filter(capital_event_clause())}
    expected = {t.raw_description for t in session.query(Transaction) if is_capital_event(t.category, t.subcategory)}
    not_in_clause = {t.raw_description for t in session.query(Transaction).filter(~capital_event_clause())}
    assert in_clause == expected
    assert in_clause | not_in_clause == {f"row {i}" for i in range(len(pairs))}   # no NULL rows dropped


def test_apply_scope_filters_a_query_and_rejects_unknown_values(session):
    from categorisation.capital_events import apply_scope

    account_id = session.query(Account).one().id
    for desc, cat, sub in [("a", "Groceries", None), ("b", "Investment", "Property Purchase"), ("c", None, None)]:
        session.add(Transaction(account_id=account_id, date=date(2026, 1, 1), amount=-1.0, raw_description=desc,
                                type="Expense", category=cat, subcategory=sub))
    session.commit()

    def names(scope):
        return {t.raw_description for t in apply_scope(session.query(Transaction), scope)}

    assert names("all") == {"a", "b", "c"}
    assert names("operating") == {"a", "c"}      # a row with no category is day-to-day, not dropped
    assert names("capital") == {"b"}
    with pytest.raises(ValueError, match="scope"):
        apply_scope(session.query(Transaction), "Operating")


def test_reclassify_does_not_overwrite_a_row_the_user_already_categorised(session):
    # A hand-corrected row carries a real category; only unplaced rows (no category / Miscellaneous)
    # and the old groupless Transfer typing are swept.
    corrected = _tx(session, "ONLINE X JC to Barkly HL MAYEKAR A", -100.0, type="Expense", category="Gifts & Donations")
    unplaced = _tx(session, "ONLINE Y JC to Barkly HL MAYEKAR A", -100.0, type="Expense", category="Miscellaneous")
    assert reclassify_capital_events(session) == 1
    assert corrected.category == "Gifts & Donations"
    assert unplaced.subcategory == "Loan Paydown"
