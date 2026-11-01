"""
Shared helpers for rows that are `Transfer`s by their text alone, with no counterpart row and so no
TransferGroup: loan movements, card payments whose other leg isn't imported yet, and share-portfolio
contributions. Each kind has its own predicate (`is_loan_movement`, `is_card_payment`,
`is_investment_contribution`); typing a matching row and sweeping stored rows are done here once.

Safe without a group: GET /summary and the Portfolio queries exclude by `type`, not by group.
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

from backend.models import Transaction
from backend.needs_review_reasons import TRANSFER_MATCH, should_supersede


def mark_as_lone_transfer(tx: Transaction) -> None:
    """Type one row as a Transfer with no counterpart row; its category no longer means anything."""
    tx.type = "Transfer"
    tx.category = None
    tx.subcategory = None
    tx.is_refund = False
    if tx.needs_review_reason is None or should_supersede(tx.needs_review_reason, TRANSFER_MATCH):
        tx.needs_review = False
        tx.needs_review_reason = None


def reclassify_where(session: Session, predicate: Callable[[str, float], bool]) -> int:
    """
    Type every stored, non-superseded, non-Transfer row whose (description, amount) satisfies
    `predicate` as a lone Transfer. Idempotent; the caller commits. Returns how many rows changed.
    """
    # .all(): the loop changes `type`, which the filter reads, so don't iterate a live query.
    rows = (
        session.query(Transaction)
        .filter(Transaction.type != "Transfer", Transaction.superseded_by_id.is_(None))
        .all()
    )
    changed = 0
    for tx in rows:
        if predicate(tx.raw_description, tx.amount):
            mark_as_lone_transfer(tx)
            changed += 1
    session.flush()
    return changed
