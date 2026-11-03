"""
Money sent to one of the user's own accounts whose statements aren't imported yet.

Today that is the Macquarie account (MAC): a debit worded `JC to Macquarie`, `JC to Mac CMA`,
`AC to MCA`, `Macquarie CM Acc` or `transfer to mac acc` is a move between the user's own accounts,
so it is a `Transfer` by its text alone, with no TransferGroup until a counterpart exists. When the MAC
statements are imported, the credit side pairs with it by exact amount and date (Tier 2): a lone debit
like this is the one groupless Transfer detection still searches for and offers as a partner
(`transfers.detection.is_lone_own_account_transfer`), and its partner must sit on a Macquarie account.

Only debits are matched: a credit worded `Macquarie ...` could be interest or a dividend.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from transfers.lone_transfers import reclassify_where

# The user's own wording, as it appears on his statements: "JC to Macquarie", "AC to MCA", "JC to Mac CMA",
# "transfer to mac acc", "Macquarie CM Acc". A payee that merely contains the name ("BPAY to Macquarie
# University", "Payment to Macquarie Group") has no account nickname in front and is not matched.
_MACQUARIE_RE = re.compile(
    r"\b(?:JC|AC|RC|transfer)\s+to\s+(?:Macquarie(?!\s+(?:University|Group)\b)|Mac\s*CMA|Mac\s*Acc|MCA)\b"
    r"|\bMacquarie\s+CM\s+Acc\b",
    re.IGNORECASE,
)


# The account holders' own names. They appear on both sides of a transfer between their accounts, so they
# say nothing about whether two rows belong together (transfers/listing.py), and a payment that names one
# of them is plausibly a move to their own account. This is a personal project for one household: edit
# this list for a different one.
HOUSEHOLD_NAMES = frozenset({"ROHAN", "ANILA", "MAYEKAR"})


def names_a_household_member(raw_description: str) -> bool:
    return any(w in HOUSEHOLD_NAMES for w in re.findall(r"[A-Za-z0-9]{2,}", raw_description.upper()))


def is_own_account_transfer(raw_description: str, amount: float) -> bool:
    return amount < 0 and _MACQUARIE_RE.search(raw_description) is not None


def reclassify_own_account_transfers(session: Session) -> int:
    """Type stored debits to the user's Macquarie account as `Transfer`. Idempotent; caller commits."""
    return reclassify_where(session, is_own_account_transfer)
