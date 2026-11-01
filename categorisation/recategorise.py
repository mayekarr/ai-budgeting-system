from __future__ import annotations

"""
Re-apply the current categorisation rules to rows the rules could not place at upload time.

A rule added after a row was imported (for example a newly seen rental agent) never reaches that row
on its own: rules run once, at upload. This picks up only rows still sitting on the unplaced default
(`Miscellaneous` with confidence below 1 or unset; a manual correction or a bank/rule match always has 1.0),
never a Transfer. A review flag about the category (`llm_unavailable` / `low_confidence_category`) is
cleared once a rule places the row; an unrelated one (`unrecognised_account`) stays live. Idempotent.
The caller commits.
"""

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.models import Transaction
from backend.needs_review_reasons import LLM_UNAVAILABLE, LOW_CONFIDENCE_CATEGORY
from categorisation.rules import match_rule

_CATEGORY_REASONS = (LLM_UNAVAILABLE, LOW_CONFIDENCE_CATEGORY)


def recategorise_unreviewed(session: Session) -> int:
    """Categorise unplaced rows that a rule now matches; returns how many rows changed."""
    rows = (
        session.query(Transaction)
        .filter(
            Transaction.type != "Transfer",
            Transaction.superseded_by_id.is_(None),
            Transaction.category == "Miscellaneous",
            or_(Transaction.confidence_score.is_(None), Transaction.confidence_score < 1.0),
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
        if tx.needs_review_reason is None or tx.needs_review_reason in _CATEGORY_REASONS:
            tx.needs_review = False
            tx.needs_review_reason = None
        changed += 1
    session.flush()
    return changed
