from __future__ import annotations

"""
`is_refund` detection, per docs/design-logic-and-ux.md §1.1's ranked signals and the ATO tax-refund
scoped exception (docs/product-requirements.md §4.2).

Ranked, first match wins:
1. ATO tax-refund override — checked FIRST (a short-circuit, not a race with the signals below):
   routes to Income, not netted.
2. Explicit bank signal (transaction type / bank category text says refund).
3. Description keyword backstop, for formats with no dedicated type column.

A refund signal on a counterparty that resolves to neither a known AccountAlias nor a known
CategorisationRule merchant (§1.2's shared check) is a real ambiguity — it might be a genuine
person-to-person reimbursement (Income, not a merchant refund) or a mislabeled refund — so it's
flagged for review instead of silently netted.
"""

import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from backend.models import AccountAlias, CategorisationRule
from categorisation.rules import pattern_matches
from transfers.aliases import alias_matches_text

_ATO_PATTERN = re.compile(r"\bATO\b|TAX REFUND", re.IGNORECASE)
_BANK_SIGNAL_TYPES = {"CREDIT CARD REFUND"}
_KEYWORD_PATTERN = re.compile(r"\bREFUND\b|\bRETURN\b", re.IGNORECASE)


@dataclass
class RefundDecision:
    is_refund: bool
    route_to_income: bool
    needs_review: bool


def _has_hard_bank_signal(raw_transaction_type: str) -> bool:
    """A structured transaction-type field the bank sets deliberately — trusted on its own."""
    return raw_transaction_type in _BANK_SIGNAL_TYPES


def _has_soft_signal(bank_category: Optional[str], raw_description: str) -> bool:
    """
    A category label or keyword — the kind of signal §4.1 found unreliable on its own (e.g. the
    real AC dinner-split P2P entries the bank also tags "Refund"). Needs counterparty resolution.
    """
    if bank_category and "refund" in bank_category.lower():
        return True
    return bool(_KEYWORD_PATTERN.search(raw_description))


def _resolves_to_known_counterparty(session: Session, raw_description: str) -> bool:
    for alias in session.query(AccountAlias).all():
        if alias_matches_text(alias.raw_identifier, raw_description):
            return True

    for rule in session.query(CategorisationRule).filter(CategorisationRule.is_active.is_(True)).all():
        if pattern_matches(rule.pattern, rule.match_type, raw_description):
            return True
    return False


def detect_refund(
    session: Session,
    *,
    raw_description: str,
    amount: float,
    raw_transaction_type: str = "",
    bank_category: Optional[str] = None,
) -> RefundDecision:
    # The ATO exception is specifically about money coming BACK (a refund/rebate). A debit paying
    # a tax bill to the ATO also mentions "ATO" in its description but is a real Expense, not
    # Income — the pattern match alone can't tell those apart, the sign can.
    if amount > 0 and _ATO_PATTERN.search(raw_description):
        return RefundDecision(is_refund=False, route_to_income=True, needs_review=False)

    if _has_hard_bank_signal(raw_transaction_type):
        return RefundDecision(is_refund=True, route_to_income=False, needs_review=False)

    if not _has_soft_signal(bank_category, raw_description):
        return RefundDecision(is_refund=False, route_to_income=False, needs_review=False)

    if _resolves_to_known_counterparty(session, raw_description):
        return RefundDecision(is_refund=True, route_to_income=False, needs_review=False)

    # Refund-signaled, but the counterparty is neither a known account nor a known merchant —
    # ambiguous, per §1.2. Flag rather than guess.
    return RefundDecision(is_refund=False, route_to_income=False, needs_review=True)
