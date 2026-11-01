"""
Money sent to one of the user's own accounts whose statements aren't imported yet.

Today that is the Macquarie account (MAC): a debit worded `JC to Macquarie`, `JC to Mac CMA`,
`AC to MCA`, `Macquarie CM Acc` or `transfer to mac acc` is a move between the user's own accounts,
so it is a `Transfer` by its text alone, with no counterpart row and no TransferGroup. When the MAC
statements are imported, the credit side pairs with it through Tier-1 matching (a lone Transfer is
still a candidate there).

Only debits are matched: a credit worded `Macquarie ...` could be interest or a dividend.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from transfers.lone_transfers import reclassify_where

_MACQUARIE_RE = re.compile(
    r"\bto\s+(?:Macquarie|Mac\s*CMA|Mac\s*Acc|MCA)\b|\bMacquarie\s+CM\s+Acc\b",
    re.IGNORECASE,
)


def is_own_account_transfer(raw_description: str, amount: float) -> bool:
    return amount < 0 and _MACQUARIE_RE.search(raw_description) is not None


def reclassify_own_account_transfers(session: Session) -> int:
    """Type stored debits to the user's Macquarie account as `Transfer`. Idempotent; caller commits."""
    return reclassify_where(session, is_own_account_transfer)
