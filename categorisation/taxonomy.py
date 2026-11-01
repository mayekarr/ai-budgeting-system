from __future__ import annotations

"""
The merged taxonomy (docs/product-requirements.md §4.2): finalized at 16 categories on 2026-08-18,
17 since `Investment` was added 2026-11-01.

`Refund` is deliberately absent: refunds are an `is_refund` attribute on a Transaction (except the
ATO tax-refund exception, which lives under Income). Investments are modeled as a separate Asset
entity; the `Investment` spend category (added 2026-11-01, Rohan's call) only holds capital outlays
such as a property purchase.

Income's `Rental Income` and Car's `Charging` subcategories added 2026-09-25 (Rohan's call,
docs/next-steps.md) after a real investment-property rent credit and a real EV-charging debit each
had nowhere to go but a generic catch-all. On 2026-11-01, for the FR-9g/9h/9j one-off capital events,
Income gained `Property Sale Proceeds` and `Investment Sale Proceeds`, and the new `Investment`
category got `Property Purchase`.
"""

TAXONOMY: dict[str, list[str]] = {
    "Income": ["Salary", "Interest", "Dividends & Distributions", "Rental Income", "Tax Refund", "Government Rebate", "Property Sale Proceeds", "Investment Sale Proceeds", "Other"],
    "Housing": ["Rent", "Mortgage EMI", "Home Insurance", "Utility Bills", "Maintenance/Content"],
    "Groceries": [],
    "Cafes & Restaurants": ["Restaurants & Takeaway", "Cafes & Coffee"],
    "Transport": ["Public Transport", "Taxis & Rideshare", "Parking & Tolls"],
    "Car": ["EMI", "Insurance", "Petrol", "Charging", "Registration", "Other"],
    "Travel & Holidays": ["Flights", "Accommodation", "Attractions & Events", "Other"],
    "Shopping": ["Clothes", "Electronics & Technology", "Homeware", "Other"],
    "Health & Medical": ["Medical", "Gym & Fitness"],
    "Insurance": ["Life/TPD/Income Protection", "Critical Illness", "Content (non-home)"],
    "Kids & Family": ["School Fees", "Childcare", "Activities", "Pocket Money", "Other"],
    "Gifts & Donations": ["Gifts", "Donations"],
    "Loans & Finance": ["Loan Repayment", "Loan Interest", "Financial Advice Fees"],
    "Services & Subscriptions": ["Phone & Internet", "Media/Streaming", "Other"],
    "Government & Tax": ["Tax Paid", "Government Fees"],
    "Investment": ["Property Purchase"],
    "Miscellaneous": [],
}

CATEGORIES: list[str] = list(TAXONOMY.keys())


def is_valid_category(category: str, subcategory: str | None = None) -> bool:
    """Validate a (category, subcategory) pair against the taxonomy."""
    if category not in TAXONOMY:
        return False
    if subcategory is None:
        return True
    return subcategory in TAXONOMY[category]
