from __future__ import annotations

"""
Inter-account transfer detection (FR-9c/9d/9e).

Tier 1 (signal-based, high confidence): every candidate counterpart must resolve through a
registered AccountAlias or a shared bank reference number — this is the single mechanism that
structurally keeps external parties (a dependent, a tradesperson, a friend paying back a dinner
split) out of Transfer classification, per docs/design-logic-and-ux.md §2.1: they simply never
match an alias, so they're never candidates in the first place, not excluded by a bolted-on
denylist.

Tier 2 (heuristic pairing, J5, docs/design-logic-and-ux.md §2.3): when Tier 1 finds nothing, falls
back to amount/date/sign coincidence alone across two of the user's own (already-registered)
accounts — no alias or reference-number text needed, since §2.1's candidate-pool restriction is
already satisfied by every Transaction being FK'd to a real Account. Three confidence bands:
  - High (exact amount, same day): auto-tagged Transfer, no review.
  - Medium (exact amount within the date window, or near-equal amount same day): auto-tagged
    Transfer, but flagged needs_review as a non-blocking soft confirmation.
  - Low (near-equal amount, within the date window only): NOT auto-tagged — flagged needs_review
    with the match left for the user to confirm/reject (J5's review queue).
"""

import re
from datetime import date as date_type, timedelta
from typing import Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from backend.models import Account, AccountAlias, Transaction, TransferGroup
from backend.needs_review_reasons import TRANSFER_MATCH
from transfers.aliases import alias_matches_text

_REFERENCE_TOKEN_RE = re.compile(r"\b[A-Za-z]{1,3}\d{6,}\b")
_DATE_WINDOW = timedelta(days=3)

# Tier 2 tunable defaults (docs/design-logic-and-ux.md §2.3/§4) — not locked, revisit with real
# data volume.
_TIER2_BUSINESS_DAY_WINDOW = 2
_TIER2_AMOUNT_TOLERANCE_FLAT = 2.0
_TIER2_AMOUNT_TOLERANCE_PCT = 0.01


def _find_account_via_alias_in_text(session: Session, text: str, exclude_account_id: int) -> Optional[int]:
    aliases = session.query(AccountAlias).filter(AccountAlias.account_id != exclude_account_id).all()
    for alias in aliases:
        if alias_matches_text(alias.raw_identifier, text):
            return alias.account_id
    return None


def _reference_tokens(text: str) -> list[str]:
    return _REFERENCE_TOKEN_RE.findall(text)


def _find_counterpart_via_reference_number(session: Session, tx: Transaction) -> Optional[Transaction]:
    for token in _reference_tokens(tx.raw_description):
        candidate = (
            session.query(Transaction)
            .filter(
                Transaction.id != tx.id,
                Transaction.account_id != tx.account_id,
                Transaction.raw_description.contains(token),
                Transaction.amount == -tx.amount,  # opposite sign, same magnitude — the same transfer
            )
            .first()
        )
        if candidate is not None:
            return candidate
    return None


def _find_counterpart_via_alias(session: Session, tx: Transaction) -> Optional[Transaction]:
    other_account_id = _find_account_via_alias_in_text(session, tx.raw_description, exclude_account_id=tx.account_id)
    if other_account_id is None:
        return None

    window_start = tx.date - _DATE_WINDOW
    window_end = tx.date + _DATE_WINDOW
    candidates = (
        session.query(Transaction)
        .filter(
            Transaction.id != tx.id,
            Transaction.account_id == other_account_id,
            # Opposite sign AND same magnitude — Tier-1 is meant to be deterministic; two
            # different-amount transactions between the same accounts within the window must not
            # be linked just because a counterpart account was named (amount fuzziness is Tier-2's
            # job, increment 4).
            Transaction.amount == -tx.amount,
            Transaction.date >= window_start,
            Transaction.date <= window_end,
        )
        .all()
    )
    if not candidates:
        return None
    # When more than one candidate matches (e.g. two genuinely separate transfers of the same
    # amount between the same two accounts, a few days apart), the closest date is almost always
    # the true pair — picking an arbitrary one (e.g. always the earliest) risks merging two
    # unrelated transfers into one group and leaving the other pair permanently unlinked. Two
    # candidates equally close (the same date) is a genuine ambiguity Tier-1 can't resolve safely;
    # that residual case belongs to Tier-2's confidence scoring and review queue (increment 4/J5).
    return min(candidates, key=lambda c: abs((c.date - tx.date).days))


def _link(session: Session, tx: Transaction, counterpart: Transaction, tier: int, confidence: float = 1.0) -> None:
    group = counterpart.transfer_group or tx.transfer_group
    if group is None:
        group = TransferGroup(detection_tier=tier, confidence=confidence)
        session.add(group)
        session.flush()

    tx.transfer_group = group
    counterpart.transfer_group = group
    tx.type = "Transfer"
    counterpart.type = "Transfer"
    session.commit()


def _add_business_days(d: date_type, n: int) -> date_type:
    step = 1 if n > 0 else -1
    remaining = abs(n)
    while remaining > 0:
        d += timedelta(days=step)
        if d.weekday() < 5:  # Mon-Fri
            remaining -= 1
    return d


def _amounts_exact_opposite(a: float, b: float) -> bool:
    return a == -b


def _amounts_near_equal_opposite(a: float, b: float) -> bool:
    """Opposite sign, magnitude within tolerance (<=$2 or 1%, whichever is larger) — §2.3."""
    if (a < 0) == (b < 0):  # must be opposite sign; same-sign is never a transfer leg
        return False
    tolerance = max(_TIER2_AMOUNT_TOLERANCE_FLAT, _TIER2_AMOUNT_TOLERANCE_PCT * max(abs(a), abs(b)))
    return abs(abs(a) - abs(b)) <= tolerance


def _tier2_band(tx_date: date_type, candidate_date: date_type, exact_amount: bool) -> str:
    same_day = tx_date == candidate_date
    if exact_amount and same_day:
        return "high"
    if exact_amount or same_day:  # exact-within-window, or near-equal-same-day
        return "medium"
    return "low"  # near-equal, within window only


def _find_tier2_candidates(session: Session, tx: Transaction) -> list[tuple[Transaction, str]]:
    """Every opposite-sign, near-equal-amount, in-window candidate on a different account, each
    tagged with its confidence band (§2.3). §2.1's candidate-pool restriction is automatically
    satisfied — every Transaction is FK'd to a real Account, so no alias check is needed here."""
    window_start = _add_business_days(tx.date, -_TIER2_BUSINESS_DAY_WINDOW)
    window_end = _add_business_days(tx.date, _TIER2_BUSINESS_DAY_WINDOW)
    rows = (
        session.query(Transaction)
        .filter(
            Transaction.id != tx.id,
            Transaction.account_id != tx.account_id,
            Transaction.date >= window_start,
            Transaction.date <= window_end,
            # A superseded PENDING row (backend/database.py's pending<->settled reconciliation) is
            # a shadow of its SETTLED counterpart, not a second real transaction — matching against
            # it would risk transfer-tagging a row that rollups already exclude, for a real-world
            # charge only the settled row represents.
            Transaction.superseded_by_id.is_(None),
            # A candidate already linked into some other TransferGroup must not be pulled into a
            # new, unrelated one on pure amount/date coincidence — Tier 2 only ever proposes a
            # link between two rows that are BOTH still unresolved. (`tx` itself is guaranteed
            # unlinked here too: process_transfer_detection already returns early for
            # type=="Transfer".) Mirrors the same guard backend/api.py's manual
            # confirm_transfer_with_id action applies.
            Transaction.transfer_group_id.is_(None),
            # The ATO tax-refund override (§4.2's scoped exception) is a deliberate, confident
            # classification — a coincidental opposite-amount/same-day match on another account
            # must never be allowed to reclassify it as a Transfer via pure heuristic coincidence,
            # same reasoning the upload handler already applies when deciding whether to run
            # detection on the ATO row itself (backend/api.py). Enforced here too so a match
            # approaching from the *other* side (this row is the one being searched on) can't
            # sneak the ATO row in as someone else's counterpart.
            # coalesce(...) avoids SQL's three-valued-logic trap: category/subcategory are
            # nullable, and `~and_(category == 'Income', ...)` evaluates to NULL (not TRUE) for a
            # row with a NULL category — which a WHERE clause silently drops, wrongly excluding
            # every plain uncategorised row instead of only the ATO ones.
            ~and_(
                func.coalesce(Transaction.category, "") == "Income",
                func.coalesce(Transaction.subcategory, "") == "Tax Refund",
            ),
        )
        .all()
    )
    candidates = []
    for row in rows:
        if not _amounts_near_equal_opposite(tx.amount, row.amount):
            continue
        exact = _amounts_exact_opposite(tx.amount, row.amount)
        band = _tier2_band(tx.date, row.date, exact)
        candidates.append((row, band))
    return candidates


_BAND_RANK = {"high": 2, "medium": 1, "low": 0}


def _best_tier2_candidate(session: Session, tx: Transaction) -> Optional[tuple[Transaction, str]]:
    candidates = _find_tier2_candidates(session, tx)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda pair: (_BAND_RANK[pair[1]], -abs((pair[0].date - tx.date).days), -abs(abs(pair[0].amount) - abs(tx.amount))),
    )


_TIER2_MEDIUM_CONFIDENCE = 0.6


def _process_tier2(session: Session, tx: Transaction) -> None:
    found = _best_tier2_candidate(session, tx)
    if found is None:
        return
    candidate, band = found

    if band == "high":
        _link(session, tx, candidate, tier=2, confidence=1.0)
        return

    if band == "medium":
        _link(session, tx, candidate, tier=2, confidence=_TIER2_MEDIUM_CONFIDENCE)
        _flag_transfer_match(tx, candidate)
        session.commit()
        return

    # Low confidence: not auto-tagged — surfaced in the review queue (J5) for the user to
    # confirm/reject rather than guessed at (docs/design-logic-and-ux.md §2.3).
    _flag_transfer_match(tx, candidate)
    session.commit()


def _flag_transfer_match(tx: Transaction, candidate: Transaction) -> None:
    """
    Flags both rows needs_review, but never overwrites an existing needs_review_reason: a row
    already flagged unrecognised_account (about the account itself, not this categorisation) or
    refund_ambiguity/low_confidence_category (still live for a Low-band match, since `type` isn't
    changed for those) must not have that concern silently replaced and lost — first reason set
    wins. A High/Medium-band row still gets needs_review_reason=transfer_match if it had no prior
    flag, so the queue can show the (non-blocking) transfer confirmation.
    """
    for member in (tx, candidate):
        member.needs_review = True
        if member.needs_review_reason is None:
            member.needs_review_reason = TRANSFER_MATCH


def process_transfer_detection(session: Session, tx: Transaction) -> None:
    """
    Run transfer detection for one transaction: Tier 1 (signal-based) first, falling back to
    Tier 2 (heuristic pairing, J5) only when Tier 1 finds nothing. Leaves the transaction's `type`
    untouched (whatever categorisation already assigned) when neither tier finds a match.
    """
    if tx.type == "Transfer":
        return  # already linked

    counterpart = _find_counterpart_via_reference_number(session, tx)
    if counterpart is None:
        counterpart = _find_counterpart_via_alias(session, tx)
    if counterpart is not None:
        _link(session, tx, counterpart, tier=1)
        return

    _process_tier2(session, tx)


def find_suggested_transfer_match(session: Session, tx: Transaction) -> Optional[Transaction]:
    """
    Recompute the current best Tier-2 candidate for a transaction flagged needs_review with
    reason=transfer_match but not yet linked (the Low-confidence case, §2.3) — used by the J5
    review-queue API to show a suggested counterpart without persisting an unconfirmed link.
    """
    found = _best_tier2_candidate(session, tx)
    return found[0] if found else None
