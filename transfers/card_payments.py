from __future__ import annotations

"""
Credit-card payments are `Transfer`s (docs/product-requirements.md FR-9e): money moving from the
user's own account to pay off the user's own card.

  - The card side is a credit worded exactly `DIRECT DEBIT PAYMENT`.
  - The paying side is a debit worded `<card number> NAB CARD AUTOPAY ...`.

Normally transfer detection pairs the two legs. This module is the fallback for a leg whose
counterpart has not been imported yet (a statement that ends a few days before the card's): the text
alone says it is a card payment, so it must not sit in the totals as income or spending meanwhile.
It only runs for rows detection did not pair, and the later-arriving counterpart still pairs with it
through Tier-1 alias matching.
"""

import re

from sqlalchemy.orm import Session

from backend.models import Transaction
from backend.needs_review_reasons import TRANSFER_MATCH, should_supersede

_CARD_SIDE_RE = re.compile(r"^\s*DIRECT DEBIT PAYMENT\s*$", re.IGNORECASE)
_PAYING_SIDE_RE = re.compile(r"\bNAB CARD AUTOPAY\b", re.IGNORECASE)


def is_card_payment(raw_description: str, amount: float) -> bool:
    if amount > 0:
        return _CARD_SIDE_RE.search(raw_description) is not None
    if amount < 0:
        return _PAYING_SIDE_RE.search(raw_description) is not None
    return False


def mark_as_lone_transfer(tx: Transaction) -> None:
    """Type one row as a Transfer with no counterpart row; its category no longer means anything."""
    tx.type = "Transfer"
    tx.category = None
    tx.subcategory = None
    tx.is_refund = False
    if tx.needs_review_reason is None or should_supersede(tx.needs_review_reason, TRANSFER_MATCH):
        tx.needs_review = False
        tx.needs_review_reason = None


def reclassify_card_payments(session: Session) -> int:
    """Type stored, still-unpaired card payments as `Transfer`. Idempotent; the caller commits."""
    rows = (
        session.query(Transaction)
        .filter(Transaction.type != "Transfer", Transaction.superseded_by_id.is_(None))
        .all()
    )
    changed = 0
    for tx in rows:
        if is_card_payment(tx.raw_description, tx.amount):
            mark_as_lone_transfer(tx)
            changed += 1
    session.flush()
    return changed
