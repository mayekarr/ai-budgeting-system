"""
Periodic contributions to the share portfolio are `Transfer`s (Rohan, 2026-11-01): money moving from
the user's own account into the user's own investment, not spending.

The real case is the $750 `MLC MKIS` debit paid regularly from Oct 2019 to Apr 2022. The MLC
statements aren't imported, so there is no counterpart row to pair with; the text decides (see
transfers/lone_transfers.py). The one `MLC MKIS CREDITS` credit (the $284,903.24 sale payout,
2022-04-19) is real income and is not matched: it is a credit and its text says CREDITS.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from transfers.lone_transfers import reclassify_where

# Tolerant of the export's spacing, and of CREDIT/CREDITS wording after the name.
_CONTRIBUTION_RE = re.compile(r"\bMLC\s+MKIS\b(?!\s*CREDIT)", re.IGNORECASE)


def is_investment_contribution(raw_description: str, amount: float) -> bool:
    return amount < 0 and _CONTRIBUTION_RE.search(raw_description) is not None


def reclassify_investment_contributions(session: Session) -> int:
    """Type stored contributions as `Transfer`. Idempotent; the caller commits."""
    return reclassify_where(session, is_investment_contribution)
