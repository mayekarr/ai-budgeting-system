from __future__ import annotations

"""
The finalized 16-category merged taxonomy (docs/product-requirements.md §4.2).

`Refund` and `Investment` are deliberately absent: refunds are an `is_refund` attribute on a
Transaction (except the ATO tax-refund exception, which lives under Income), and investments are
modeled as a separate Asset entity, not a spend category.
"""

TAXONOMY: dict[str, list[str]] = {
    "Income": ["Salary", "Interest", "Dividends & Distributions", "Tax Refund", "Government Rebate", "Other"],
    "Housing": ["Rent", "Mortgage EMI", "Home Insurance", "Utility Bills", "Maintenance/Content"],
    "Groceries": [],
    "Cafes & Restaurants": ["Restaurants & Takeaway", "Cafes & Coffee"],
    "Transport": ["Public Transport", "Taxis & Rideshare", "Parking & Tolls"],
    "Car": ["EMI", "Insurance", "Petrol", "Registration", "Other"],
    "Travel & Holidays": ["Flights", "Accommodation", "Attractions & Events", "Other"],
    "Shopping": ["Clothes", "Electronics & Technology", "Homeware", "Other"],
    "Health & Medical": ["Medical", "Gym & Fitness"],
    "Insurance": ["Life/TPD/Income Protection", "Critical Illness", "Content (non-home)"],
    "Kids & Family": ["School Fees", "Childcare", "Activities", "Pocket Money", "Other"],
    "Gifts & Donations": ["Gifts", "Donations"],
    "Loans & Finance": ["Loan Repayment", "Loan Interest", "Financial Advice Fees"],
    "Services & Subscriptions": ["Phone & Internet", "Media/Streaming", "Other"],
    "Government & Tax": ["Tax Paid", "Government Fees"],
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
