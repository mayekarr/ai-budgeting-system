"""
Re-apply the current categorisation rules to rows the rules could not place at upload time.

A rule added after a row was imported (for example a newly seen rental agent) never reaches that row
on its own: rules run once, at upload. This picks up only rows still sitting on the unplaced default
(`Miscellaneous` with confidence below 1 or unset; a manual correction or a bank/rule match always has 1.0),
never a Transfer. A review flag about the category (`llm_unavailable` / `low_confidence_category`) is
cleared once a rule places the row; any other flag (`unrecognised_account`, or one with no stored reason) stays live. Idempotent.
The caller commits.
"""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.models import Transaction
from backend.needs_review_reasons import LLM_UNAVAILABLE, LOW_CONFIDENCE_CATEGORY
from categorisation.rules import first_matching_rule, load_active_rules

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
    rules = load_active_rules(session)
    changed = 0
    for tx in rows:
        match = first_matching_rule(rules, tx.raw_description)
        if match is None:
            continue
        tx.category, tx.subcategory = match.category, match.subcategory
        tx.confidence_score = match.confidence
        if tx.needs_review_reason in _CATEGORY_REASONS:
            tx.needs_review = False
            tx.needs_review_reason = None
        changed += 1
    session.flush()
    return changed


def place_unplaced_row(rules, tx: Transaction) -> None:
    """
    Give a row that has lost its category one again: a rule's if one matches, otherwise the unplaced
    `Miscellaneous` default, queued for review like any row nothing could categorise. Used when a row
    stops being a Transfer (a rejected pair, a freed group), because a transfer link may have wiped its
    category. A row that still has a category, and any refund flag it carried, is left alone.
    """
    if tx.category is not None:
        return
    tx.is_refund = False
    match = first_matching_rule(rules, tx.raw_description)
    if match is not None:
        tx.category, tx.subcategory = match.category, match.subcategory
        return
    tx.category, tx.subcategory, tx.confidence_score = "Miscellaneous", None, 0.0
    if tx.needs_review_reason is None:
        tx.needs_review, tx.needs_review_reason = True, LLM_UNAVAILABLE
