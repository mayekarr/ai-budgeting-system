from __future__ import annotations

"""
Loan movements that are `Transfer`s (docs/product-requirements.md FR-9f, FR-9i): borrowed money
moving between the user's own accounts, not earnings or spending.

  - A drawdown or redraw is a credit worded `LOAN PROCEEDS FROM A/C …` / `REDRAW PROCEEDS FROM A/C …`.
  - A lump-sum paydown is a debit to one of the user's home loans, worded `… to <name> HL`
    (e.g. `JC to Barkly HL`).

Regular instalments, repayments and interest are deliberately *not* matched: they stay `Expense`
(J6's cash-flow view, because they include interest).

The loan's own statement isn't imported, so there is no counterpart row to pair with and transfer
detection can't type these. They are recognised from the text alone, with no TransferGroup. That is
safe: GET /summary and the Portfolio queries exclude by `type`, not by group.
"""

import re

from sqlalchemy.orm import Session

from backend.models import Transaction
from backend.needs_review_reasons import TRANSFER_MATCH, should_supersede

_DRAWDOWN_RE = re.compile(r"\b(?:LOAN|REDRAW) PROCEEDS FROM A/C\b", re.IGNORECASE)
# "<own account nickname> to <loan name> HL", e.g. "JC to Barkly HL": a two-letter upper-case
# nickname, "to", one or two alphabetic words, then an upper-case "HL" as a whole word. Anchoring on
# the nickname keeps a payee ("Payment to Mr Smith HL", "TO KMART HL", "TO SHELL HLDG") out.
_PAYDOWN_RE = re.compile(r"\b(?-i:[A-Z]{2})\s+to\s+(?:[A-Za-z]+\s+){1,2}(?-i:HL)\b", re.IGNORECASE)


def is_loan_movement(raw_description: str, amount: float) -> bool:
    if amount > 0:
        return _DRAWDOWN_RE.search(raw_description) is not None
    if amount < 0:
        return _PAYDOWN_RE.search(raw_description) is not None
    return False


def reclassify_loan_movements(session: Session) -> int:
    """
    Type already-stored loan movements as `Transfer` (the upload path does this for new rows).
    Clears a review flag that is moot once the row is a Transfer, same rule as a transfer link;
    `unrecognised_account` is about the account, so it stays. Idempotent. The caller commits.
    Returns how many rows changed.
    """
    changed = 0
    # .all(): the loop changes `type`, which the filter reads, so don't iterate a live query.
    rows = (
        session.query(Transaction)
        .filter(Transaction.type != "Transfer", Transaction.superseded_by_id.is_(None))
        .all()
    )
    for tx in rows:
        if not is_loan_movement(tx.raw_description, tx.amount):
            continue
        tx.type = "Transfer"
        if tx.needs_review_reason is None or should_supersede(tx.needs_review_reason, TRANSFER_MATCH):
            tx.needs_review = False
            tx.needs_review_reason = None
        changed += 1
    return changed
