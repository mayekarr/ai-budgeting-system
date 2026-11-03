"""
Clear `transfer_match` review flags that no longer point at anything.

An earlier matching mode flagged a row as "maybe a transfer" without linking it. That mode is gone, but the
flags it left behind stayed: a row with `needs_review_reason = transfer_match`, in no transfer group, and
with no current candidate to pair with. The review queue shows them as "No current candidate match" and they
bury the rows that do need a decision.

A flag is cleared only when the row is in no group and nothing points at it any more. Two things still do:
- a current candidate to pair with;
- a tentative (below full confidence) pair that this row tied with: when two equal credits competed for one
  debit, the loser is flagged so the arbitrary choice stays visible, even though its competitor has since
  been taken by the winning pair.
The flag had replaced a lesser reason, so a row still waiting for a category goes back to that reason
(`llm_unavailable` when nothing could categorise it, `low_confidence_category` otherwise) instead of leaving
review; any other row is settled and its flag is simply removed. Idempotent. The caller commits.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from backend.models import Transaction, TransferGroup
from backend.needs_review_reasons import LLM_UNAVAILABLE, LOW_CONFIDENCE_CATEGORY, TRANSFER_MATCH
from transfers.detection import find_suggested_transfer_match

# Two business days either side is the Tier-2 window; four calendar days covers it across a weekend.
_TIE_WINDOW = timedelta(days=4)


def _still_waiting_for_a_category(tx: Transaction) -> bool:
    return tx.category == "Miscellaneous" and (tx.confidence_score is None or tx.confidence_score < 1.0)


def _is_alternate_for_a_tentative_pair(session: Session, tx: Transaction) -> bool:
    """Another row of the exact opposite amount, on another account and near in date, sits in a tentative pair."""
    return (
        session.query(Transaction.id)
        .join(TransferGroup, Transaction.transfer_group_id == TransferGroup.id)
        .filter(
            TransferGroup.confidence < 1.0,
            Transaction.account_id != tx.account_id,
            Transaction.amount == -tx.amount,
            Transaction.date >= tx.date - _TIE_WINDOW,
            Transaction.date <= tx.date + _TIE_WINDOW,
        )
        .first()
        is not None
    )


def clear_stale_transfer_match_flags(session: Session) -> int:
    """Returns how many rows were changed."""
    rows = (
        session.query(Transaction)
        .filter(
            Transaction.needs_review_reason == TRANSFER_MATCH,
            Transaction.transfer_group_id.is_(None),
            Transaction.superseded_by_id.is_(None),
        )
        .all()
    )
    changed = 0
    for tx in rows:
        if find_suggested_transfer_match(session, tx) is not None or _is_alternate_for_a_tentative_pair(session, tx):
            continue
        if _still_waiting_for_a_category(tx):
            reason = LLM_UNAVAILABLE if tx.confidence_score == 0.0 else LOW_CONFIDENCE_CATEGORY
            tx.needs_review, tx.needs_review_reason = True, reason
        else:
            tx.needs_review, tx.needs_review_reason = False, None
        changed += 1
    session.flush()
    return changed
