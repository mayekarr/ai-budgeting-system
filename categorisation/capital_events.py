"""
Capital and financing events: money that is real but not day-to-day earning or spending (Rohan,
2026-11-01, reversing the earlier "loan movements and contributions are Transfers" decisions).

  - A loan drawdown or redraw (`LOAN PROCEEDS FROM A/C ...`) is `Income / Loan Drawdown`.
  - A lump-sum paydown to an own loan (`JC to Barkly HL`) is `Loans & Finance / Loan Paydown`.
  - A periodic share-portfolio contribution (`MLC MKIS`) is `Investment / Share Portfolio Contribution`.

They stay out of `Transfer` because the money does not come back unless an investment is sold: it
is a real outflow (or inflow) of spendable cash. They are kept apart from day-to-day totals by
`is_capital_event`, which GET /summary's `scope` and the Overview switch use, together with
property sale proceeds and property purchases.

The loan and investment statements aren't imported, so these have no counterpart row: the text
alone decides, at upload and in `reclassify_capital_events`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from backend.models import Transaction
from backend.needs_review_reasons import LLM_UNAVAILABLE, LOW_CONFIDENCE_CATEGORY, REFUND_AMBIGUITY, TRANSFER_MATCH
from transfers.investment_contributions import is_investment_contribution
from transfers.loan_movements import is_loan_movement


@dataclass(frozen=True)
class CapitalTag:
    type: str
    category: str
    subcategory: str


LOAN_DRAWDOWN = CapitalTag("Income", "Income", "Loan Drawdown")
LOAN_PAYDOWN = CapitalTag("Expense", "Loans & Finance", "Loan Paydown")
SHARE_CONTRIBUTION = CapitalTag("Expense", "Investment", "Share Portfolio Contribution")

# Income subcategories that are capital events rather than earnings.
CAPITAL_INCOME_SUBCATEGORIES = ("Property Sale Proceeds", "Investment Sale Proceeds", "Loan Drawdown")

# Reasons a text-decided tag resolves; unrecognised_account is about the account, so it stays.
_RESOLVED_REASONS = (LLM_UNAVAILABLE, LOW_CONFIDENCE_CATEGORY, REFUND_AMBIGUITY, TRANSFER_MATCH)


def is_capital_event(category: Optional[str], subcategory: Optional[str]) -> bool:
    """True for property sale/purchase, investment sale/contribution and loan drawdown/paydown."""
    if category == "Income":
        return subcategory in CAPITAL_INCOME_SUBCATEGORIES
    if category == "Investment":
        return True
    return category == "Loans & Finance" and subcategory == "Loan Paydown"


def capital_event_clause():
    """
    SQL form of `is_capital_event` over Transaction.category/subcategory. coalesce(...) keeps it
    two-valued, so `~capital_event_clause()` still returns rows with a NULL category instead of
    silently dropping them (SQL's three-valued logic).
    """
    category = func.coalesce(Transaction.category, "")
    subcategory = func.coalesce(Transaction.subcategory, "")
    return or_(
        and_(category == "Income", subcategory.in_(CAPITAL_INCOME_SUBCATEGORIES)),
        category == "Investment",
        and_(category == "Loans & Finance", subcategory == "Loan Paydown"),
    )


SCOPE_VALUES = ("all", "operating", "capital")


def apply_scope(query, scope: str):
    """
    Restrict a Transaction query to day-to-day (`operating`), capital & financing events
    (`capital`) or both (`all`). An unknown value raises rather than silently meaning `all`, so a
    typo can't leak capital events into day-to-day totals.
    """
    if scope not in SCOPE_VALUES:
        raise ValueError(f"Unknown scope {scope!r}; expected one of {SCOPE_VALUES}.")
    if scope == "operating":
        return query.filter(~capital_event_clause())
    if scope == "capital":
        return query.filter(capital_event_clause())
    return query


def classify_capital_event(raw_description: str, amount: float) -> Optional[CapitalTag]:
    """The tag a row's text alone decides, or None. A debit is a paydown, a credit a drawdown."""
    if is_loan_movement(raw_description, amount):
        return LOAN_DRAWDOWN if amount > 0 else LOAN_PAYDOWN
    if is_investment_contribution(raw_description, amount):
        return SHARE_CONTRIBUTION
    return None


def apply_capital_tag(tx: Transaction, tag: CapitalTag) -> None:
    tx.type = tag.type
    tx.category = tag.category
    tx.subcategory = tag.subcategory
    tx.is_refund = False
    tx.confidence_score = 1.0
    if tx.needs_review_reason is None or tx.needs_review_reason in _RESOLVED_REASONS:
        tx.needs_review = False
        tx.needs_review_reason = None


def reclassify_capital_events(session: Session) -> int:
    """
    Apply the text-decided tags to stored rows, including ones earlier typed `Transfer` (the old
    behaviour). Rows in a transfer group are real pairs and are never touched, and neither is a row
    already given a real category (a hand correction, or a rule that placed it): only rows with no
    category, `Miscellaneous`, or the old groupless Transfer typing are swept. Idempotent; the
    caller commits. Returns how many rows changed.
    """
    rows = (
        session.query(Transaction)
        .filter(Transaction.superseded_by_id.is_(None), Transaction.transfer_group_id.is_(None))
        .all()
    )
    changed = 0
    for tx in rows:
        tag = classify_capital_event(tx.raw_description, tx.amount)
        if tag is None:
            continue
        if (tx.type, tx.category, tx.subcategory) == (tag.type, tag.category, tag.subcategory):
            continue
        if tx.type != "Transfer" and tx.category not in (None, "Miscellaneous"):
            continue
        apply_capital_tag(tx, tag)
        changed += 1
    session.flush()
    return changed
