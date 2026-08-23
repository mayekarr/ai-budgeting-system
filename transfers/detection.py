from __future__ import annotations

"""
Tier-1 (signal-based) inter-account transfer detection (FR-9c/9d/9e tier 1).

Every candidate counterpart must resolve through a registered AccountAlias — this is the single
mechanism that structurally keeps external parties (a dependent, a tradesperson, a friend paying
back a dinner split) out of Transfer classification, per docs/design-logic-and-ux.md §2.1: they
simply never match an alias, so they're never candidates in the first place, not excluded by a
bolted-on denylist.

Tier-2 heuristic (date/amount-only) pairing and confidence scoring is deliberately NOT here — it's
increment 4's job (J5), since its whole purpose is producing medium/low-confidence matches for a
review queue that doesn't exist yet.
"""

import re
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from backend.models import Account, AccountAlias, Transaction, TransferGroup
from transfers.aliases import alias_matches_text

_REFERENCE_TOKEN_RE = re.compile(r"\b[A-Za-z]{1,3}\d{6,}\b")
_DATE_WINDOW = timedelta(days=3)


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


def _link(session: Session, tx: Transaction, counterpart: Transaction, tier: int) -> None:
    group = counterpart.transfer_group or tx.transfer_group
    if group is None:
        group = TransferGroup(detection_tier=tier, confidence=1.0)
        session.add(group)
        session.flush()

    tx.transfer_group = group
    counterpart.transfer_group = group
    tx.type = "Transfer"
    counterpart.type = "Transfer"
    session.commit()


def process_transfer_detection(session: Session, tx: Transaction) -> None:
    """
    Run Tier-1 transfer detection for one transaction, linking it to a TransferGroup if a
    high-confidence signal identifies a counterpart. Leaves the transaction's `type` untouched
    (whatever categorisation already assigned) when no signal is found.
    """
    if tx.type == "Transfer":
        return  # already linked

    counterpart = _find_counterpart_via_reference_number(session, tx)
    if counterpart is None:
        counterpart = _find_counterpart_via_alias(session, tx)
    if counterpart is None:
        return

    _link(session, tx, counterpart, tier=1)
