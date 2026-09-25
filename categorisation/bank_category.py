from __future__ import annotations

"""
Derives a category/subcategory from the bank's own "Category" column
(ingestion/nab_format.py's `raw_bank_category`), for transactions no CategorisationRule matched.

Added 2026-09-25 after a live defect-triage session found the Claude fallback permanently
unavailable (no ANTHROPIC_API_KEY, ever -- docs/product-requirements.md §4.3.1) leaving every
rule-unmatched transaction stuck in Miscellaneous, while the bank's own Category field was being
parsed and then thrown away. Spot-checking the real data: 409 of 422 rows across the 4 real,
currently-supported account files (transaction-files/) carry a non-blank bank Category, and every
manually-checked case (Donations, Insurance, Cafe & coffee) was correct.

This does NOT reopen §4.1's finding that bank-assigned categories are unreliable as a
*transfer/refund type* signal (e.g. a real invoice mislabelled "Transfers out") -- that's a
different, narrower question about type-detection, not general spend/income classification. The
map below deliberately excludes exactly those transfer/refund-labelled values (and "Uncategorised",
which carries no signal at all) so this module can't reintroduce the problem §4.1 found.

Consulted in backend/api.py's upload handler after CategorisationRule matching fails and before the
Claude fallback -- a rule (including a user correction, FR-9) always wins when one exists; this is
a second, more general line of defence, not a replacement for either. Deliberately does *not*
promote a CategorisationRule the way a confident LLM result does (categorisation/claude_fallback.py)
-- the bank's own data is present on essentially every row of a supported export format already, so
there's no cost to re-derive it fresh each time, and no risk of a promoted rule generalising badly
from one merchant's raw_description to an unrelated one.
"""

from typing import Optional

# Category -> (category, subcategory). Values pulled from real transaction-files/ data, not
# invented. `None` subcategory where the bank's own label doesn't distinguish which specific
# subcategory applies (e.g. plain "Insurance") -- always a valid pairing (taxonomy.is_valid_category
# permits any subcategory=None), and no worse than what a real seeded rule already does in that
# situation (e.g. the WOOLWORTHS/Groceries rule).
_BANK_CATEGORY_MAP: dict[str, tuple[str, Optional[str]]] = {
    "groceries": ("Groceries", None),
    "restaurants & takeaway": ("Cafes & Restaurants", "Restaurants & Takeaway"),
    "cafe & coffee": ("Cafes & Restaurants", "Cafes & Coffee"),
    "donations": ("Gifts & Donations", "Donations"),
    "gifts": ("Gifts & Donations", "Gifts"),
    "gym & fitness": ("Health & Medical", "Gym & Fitness"),
    "insurance": ("Insurance", None),
    "taxis & ride shares": ("Transport", "Taxis & Rideshare"),
    "medical": ("Health & Medical", "Medical"),
    "public transport": ("Transport", "Public Transport"),
    "accommodation": ("Travel & Holidays", "Accommodation"),
    "services": ("Services & Subscriptions", "Other"),
    "travel expenses": ("Travel & Holidays", "Other"),
    "other shopping": ("Shopping", "Other"),
    "utilities": ("Housing", "Utility Bills"),
    "attractions & events": ("Travel & Holidays", "Attractions & Events"),
    "flights": ("Travel & Holidays", "Flights"),
    "phone & internet": ("Services & Subscriptions", "Phone & Internet"),
    "parking & tolls": ("Transport", "Parking & Tolls"),
    "electronics & technology": ("Shopping", "Electronics & Technology"),
    "homeware": ("Shopping", "Homeware"),
    "government": ("Government & Tax", "Government Fees"),
    "media": ("Services & Subscriptions", "Media/Streaming"),
    # Generic bank labels that don't distinguish the more specific real subcategory (Interest vs.
    # Dividends & Distributions; Loan Repayment vs. Loan Interest) -- left unset rather than
    # guessed. categorisation/seed_rules.py's more specific text rules (SALARY/WAGES, INTEREST
    # CHARGED, ...) run first and already catch the cases that matter most; this is a safety net
    # for whatever those miss.
    "investment income": ("Income", None),
    "loans": ("Loans & Finance", None),
    "income": ("Income", "Other"),
    # Deliberately excluded -- the exact categories §4.1 found unreliable as a transfer/refund type
    # signal (never listed here means categorise_from_bank_category returns None for them, same as
    # "uncategorised"): "internal transfers", "transfers out", "transfers in", "refund",
    # "credit card repayments".
}


def categorise_from_bank_category(raw_bank_category: Optional[str]) -> Optional[tuple[str, Optional[str]]]:
    """(category, subcategory) derived from the bank's own Category value, or None if there's no
    safe mapping (blank, "Uncategorised", unrecognised, or a transfer/refund-labelled value)."""
    if not raw_bank_category:
        return None
    return _BANK_CATEGORY_MAP.get(raw_bank_category.strip().lower())
