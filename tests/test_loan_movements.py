from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Account, Base, Transaction
from transfers.loan_movements import is_loan_movement, reclassify_loan_movements


@pytest.mark.parametrize(
    "description, amount",
    [
        ("LOAN PROCEEDS FROM A/C 34-188-5257", 900000.00),
        ("LOAN PROCEEDS FROM A/C 34-189-2465", 63014.45),
        ("REDRAW PROCEEDS FROM A/C 70-320-6283", 47000.00),
        ("redraw proceeds from a/c 70-320-6283", 7000.00),
        ("ONLINE N8131366871 JC to Barkly HL MAYEKAR A", -582076.00),
        ("ONLINE R2219386106 JC to Barkly HL MAYEKAR A", -33900.00),
        ("ONLINE R2219386107 AC to Hillside Crescent HL MAYEKAR A", -10000.00),
    ],
)
def test_drawdowns_redraws_and_lump_sum_paydowns_are_loan_movements(description, amount):
    assert is_loan_movement(description, amount) is True


@pytest.mark.parametrize(
    "description, amount",
    [
        # Regular instalments, repayments and interest stay Expense (J6's cash-flow view).
        ("LOAN INSTALMENT TO A/C 399934242 MAYEKAR", -244.89),
        ("LOAN REPAYMENT TO A/C 703206283 MAYEKAR A", -6489.89),
        ("INTEREST CHARGED FROM A/C 34-188-5257", -4877.79),
        ("INTERNET TRANSFER Ex Loan Repayment Rohan Mayekar", -1000.00),
        ("ONLINE K1111111111 Month ex loanrepay MAYEKAR A", -1000.00),
        # Ordinary spending.
        ("WOOLWORTHS 3150 FOREST HILL", -35.45),
        ("PAYMENT TO SHELL HLDG PTY LTD", -80.00),
        # Too loose to trust: lower-case "hl" and digit-only words are not a home-loan name.
        ("Payment to J Smith hl", -50.00),
        ("Transfer to 12345 HL", -100.00),
        # A paydown is written "<own account nickname> to <loan name> HL", never a payee's name.
        ("Payment to Mr Smith HL", -250.00),
        ("Transfer to Kmart HL", -90.00),
        ("PAYMENT TO KMART HL", -90.00),
    ],
)
def test_instalments_interest_and_ordinary_rows_are_not_loan_movements(description, amount):
    assert is_loan_movement(description, amount) is False


def test_sign_must_match_the_kind_of_movement():
    # Money coming out of a loan is a credit; a paydown is a debit.
    assert is_loan_movement("LOAN PROCEEDS FROM A/C 34-188-5257", -900000.00) is False
    assert is_loan_movement("ONLINE N8131366871 JC to Barkly HL MAYEKAR A", 582076.00) is False


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        account = Account(name="JC")
        s.add(account)
        s.commit()
        s.info["account_id"] = account.id
        yield s


def _tx(session, description, amount, *, type_, reason=None, d=date(2025, 9, 8), **extra):
    tx = Transaction(
        account_id=session.info["account_id"], date=d, amount=amount, raw_description=description,
        type=type_, category="Miscellaneous", needs_review=reason is not None,
        needs_review_reason=reason, **extra,
    )
    session.add(tx)
    session.commit()
    return tx


def test_reclassify_turns_existing_loan_movements_into_transfers_and_clears_moot_flags(session):
    drawdown = _tx(session, "LOAN PROCEEDS FROM A/C 34-188-5257", 900000.00, type_="Income", reason="llm_unavailable")
    paydown = _tx(
        session, "ONLINE N8131366871 JC to Barkly HL MAYEKAR A", -582076.00, type_="Expense", reason="llm_unavailable"
    )
    instalment = _tx(
        session, "LOAN INSTALMENT TO A/C 399934242 MAYEKAR", -244.89, type_="Expense", reason="llm_unavailable"
    )

    changed = reclassify_loan_movements(session)

    assert changed == 2
    assert (drawdown.type, drawdown.needs_review, drawdown.needs_review_reason) == ("Transfer", False, None)
    assert (paydown.type, paydown.needs_review, paydown.needs_review_reason) == ("Transfer", False, None)
    assert (instalment.type, instalment.needs_review_reason) == ("Expense", "llm_unavailable")


def test_reclassify_is_idempotent(session):
    _tx(session, "LOAN PROCEEDS FROM A/C 34-188-5257", 900000.00, type_="Income")

    assert reclassify_loan_movements(session) == 1
    assert reclassify_loan_movements(session) == 0


def test_reclassify_keeps_an_unrecognised_account_flag(session):
    # About the account's identity, not this row's classification, so it is never cleared.
    tx = _tx(session, "LOAN PROCEEDS FROM A/C 34-188-5257", 900000.00, type_="Income", reason="unrecognised_account")

    reclassify_loan_movements(session)

    assert tx.type == "Transfer"
    assert tx.needs_review_reason == "unrecognised_account"
    assert tx.needs_review is True


def test_reclassify_ignores_superseded_and_already_transfer_rows(session):
    settled = _tx(session, "ONLINE X JC to Barkly HL MAYEKAR A", -100.00, type_="Expense")
    pending = _tx(session, "ONLINE X JC to Barkly HL MAYEKAR A", -100.00, type_="Expense", superseded_by_id=settled.id)
    linked = _tx(session, "LOAN PROCEEDS FROM A/C 34-188-5257", 5.00, type_="Transfer")

    assert reclassify_loan_movements(session) == 1  # only the settled row
    assert pending.type == "Expense"
    assert linked.type == "Transfer"
