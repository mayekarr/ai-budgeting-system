from __future__ import annotations

"""
Periodic contributions to the share portfolio are `Transfer`s (Rohan, 2026-11-01): money moving from
the user's own account into the user's own investment, not spending.

The real case is the $750 `MLC MKIS` debit paid regularly from Oct 2019 to Apr 2022. The MLC
statements aren't imported, so there is no counterpart row to pair with; the text decides, with no
TransferGroup (safe: GET /summary and the Portfolio queries exclude by `type`). The one `MLC MKIS
CREDITS` credit (the $284,903.24 sale payout, 2022-04-19) is real income and is not matched: it is a
credit and its text says CREDITS.
"""

import re

from sqlalchemy.orm import Session

from backend.models import Transaction
from transfers.card_payments import mark_as_lone_transfer

_CONTRIBUTION_RE = re.compile(r"\bMLC MKIS\b(?!\s+CREDITS)", re.IGNORECASE)


def is_investment_contribution(raw_description: str, amount: float) -> bool:
    return amount < 0 and _CONTRIBUTION_RE.search(raw_description) is not None


def reclassify_investment_contributions(session: Session) -> int:
    """Type stored contributions as `Transfer`. Idempotent; the caller commits."""
    rows = (
        session.query(Transaction)
        .filter(Transaction.type != "Transfer", Transaction.superseded_by_id.is_(None))
        .all()
    )
    changed = 0
    for tx in rows:
        if is_investment_contribution(tx.raw_description, tx.amount):
            mark_as_lone_transfer(tx)
            changed += 1
    session.flush()
    return changed
