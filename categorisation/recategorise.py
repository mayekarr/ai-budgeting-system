from __future__ import annotations

"""
Re-apply the current categorisation rules to rows the rules could not place at upload time.

A rule added after a row was imported (for example a newly seen rental agent) never reaches that row
on its own: rules run once, at upload. This picks up only rows still waiting on a category
(`llm_unavailable` / `low_confidence_category`, or an unconfident Miscellaneous that lost its flag; never a Transfer), so it never overwrites a manual
correction or a row with an unrelated review reason. Idempotent. The caller commits.
"""

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from backend.models import Transaction
from backend.needs_review_reasons import LLM_UNAVAILABLE, LOW_CONFIDENCE_CATEGORY
from categorisation.rules import match_rule


def recategorise_unreviewed(session: Session) -> int:
    """Categorise waiting rows that a rule now matches; returns how many rows changed."""
    rows = (
        session.query(Transaction)
        .filter(
            Transaction.type != "Transfer",
            Transaction.superseded_by_id.is_(None),
            or_(
                and_(
                    Transaction.needs_review.is_(True),
                    Transaction.needs_review_reason.in_((LLM_UNAVAILABLE, LOW_CONFIDENCE_CATEGORY)),
                ),
                # Still the unplaced default but no longer flagged (e.g. restored by "not a
                # transfer"). A manual correction or a bank/rule match always has confidence 1.0.
                and_(
                    Transaction.needs_review.is_(False),
                    Transaction.category == "Miscellaneous",
                    Transaction.confidence_score < 1.0,
                ),
            ),
        )
        .all()
    )
    changed = 0
    for tx in rows:
        match = match_rule(session, tx.raw_description)
        if match is None:
            continue
        tx.category, tx.subcategory = match.category, match.subcategory
        tx.confidence_score = match.confidence
        tx.needs_review = False
        tx.needs_review_reason = None
        changed += 1
    session.flush()
    return changed
