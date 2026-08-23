from __future__ import annotations

ALL_CATEGORIES = "All Categories"


def category_options(categories: list[str]) -> list[str]:
    """Prepend the "view everything" sentinel to a list of real category names."""
    return [ALL_CATEGORIES] + list(categories)


def present_categories(transactions: list[dict]) -> list[str]:
    """Distinct categories actually present among a set of transactions, sorted alphabetically."""
    return sorted({t["category"] for t in transactions if t.get("category")})
