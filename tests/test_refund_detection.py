from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import AccountAlias, Account, Base, CategorisationRule
from transfers.refunds import detect_refund


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s


def test_explicit_bank_refund_signal_is_a_refund(session):
    # Real CC example: CREDIT CARD REFUND, Spotlight Box Hill $10.
    result = detect_refund(session, raw_description="SPOTLIGHT BOX HILL BOX HILL SOUT", amount=10.0,
                            raw_transaction_type="CREDIT CARD REFUND", bank_category="Refund")

    assert result.is_refund is True
    assert result.route_to_income is False
    assert result.needs_review is False


def test_ato_tax_refund_routes_to_income_not_netted(session):
    result = detect_refund(session, raw_description="ATO TAX REFUND 2026 NOTICE", amount=450.0,
                            raw_transaction_type="DIRECT CREDIT", bank_category=None)

    assert result.is_refund is False
    assert result.route_to_income is True


def test_ato_override_takes_priority_over_generic_refund_signal(session):
    # Even if a bank tags it "Refund", the ATO pattern must win (checked first, per §4.2).
    result = detect_refund(session, raw_description="ATO TAX REFUND", amount=450.0,
                            raw_transaction_type="", bank_category="Refund")

    assert result.route_to_income is True
    assert result.is_refund is False


def test_ato_debit_paying_a_tax_bill_is_not_treated_as_income(session):
    # A real debit paying money TO the ATO also mentions "ATO" in its description — the sign is
    # what distinguishes "money back" from "money owed", the text pattern alone can't.
    result = detect_refund(session, raw_description="ATO PAYMENT BPAY TAX BILL", amount=-1200.0,
                            raw_transaction_type="BPAY", bank_category=None)

    assert result.route_to_income is False
    assert result.is_refund is False


def test_unresolved_p2p_refund_label_flags_for_review_not_netted(session):
    # Real AC example: a friend paying back a dinner split, bank-labeled "Refund", but the
    # description doesn't resolve to any known merchant rule or account alias.
    result = detect_refund(session, raw_description="HELEN SPURRrocking girls dinner", amount=61.5,
                            raw_transaction_type="TRANSFER CREDIT", bank_category="Refund")

    assert result.needs_review is True
    assert result.is_refund is False


def test_known_merchant_rule_match_lets_a_bank_labeled_refund_net_normally(session):
    session.add(CategorisationRule(pattern="SPOTLIGHT", match_type="substring", category="Shopping",
                                    priority=10, source="seeded", is_active=True))
    session.commit()

    result = detect_refund(session, raw_description="SPOTLIGHT BOX HILL", amount=10.0,
                            raw_transaction_type="", bank_category="Refund")

    assert result.is_refund is True
    assert result.needs_review is False


def test_masked_account_alias_is_recognised_via_the_same_matcher_as_transfers(session):
    # A masked alias like "453030xxxxxx7128" must resolve against real unmasked digits in the
    # description, the same masking-aware match transfers/detection.py uses — not a naive
    # substring check that would never see the literal 'x' characters in real bank text.
    account = Account(name="CC", institution="NAB", owner="Rohan", account_type="Credit Card")
    session.add(account)
    session.flush()
    session.add(AccountAlias(account_id=account.id, raw_identifier="453030xxxxxx7128"))
    session.commit()

    result = detect_refund(session, raw_description="4530307001277128 REFUND PROCESSED", amount=50.0,
                            raw_transaction_type="", bank_category="Refund")

    assert result.is_refund is True
    assert result.needs_review is False


def test_no_refund_signal_at_all_is_not_a_refund(session):
    result = detect_refund(session, raw_description="WOOLWORTHS/GLEBE ST", amount=-142.64,
                            raw_transaction_type="CREDIT CARD PURCHASE", bank_category="Groceries")

    assert result.is_refund is False
    assert result.route_to_income is False
    assert result.needs_review is False
