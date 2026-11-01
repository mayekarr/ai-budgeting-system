"""
The one question the upload path asks before saving a row: is this a Transfer by its text alone?

True for loan drawdowns/redraws and lump-sum paydowns (FR-9f/9i) and for share-portfolio
contributions. Card payments are deliberately *not* here: they should still be offered to transfer
detection first, so a real counterpart row pairs with them (the upload applies `is_card_payment` after
detection). Add a new text-only kind here and in `scripts/tidy_categories.py`, nowhere else.
"""

from __future__ import annotations

from transfers.investment_contributions import is_investment_contribution
from transfers.loan_movements import is_loan_movement


def is_text_only_transfer(raw_description: str, amount: float) -> bool:
    return is_loan_movement(raw_description, amount) or is_investment_contribution(raw_description, amount)
