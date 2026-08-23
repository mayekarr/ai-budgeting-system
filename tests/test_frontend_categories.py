from __future__ import annotations

from frontend.categories import ALL_CATEGORIES, category_options, present_categories


def test_category_options_prepends_all_categories_sentinel():
    assert category_options(["Groceries", "Transport"]) == [ALL_CATEGORIES, "Groceries", "Transport"]


def test_category_options_with_no_categories_still_offers_all():
    assert category_options([]) == [ALL_CATEGORIES]


def test_present_categories_returns_distinct_sorted_categories():
    transactions = [
        {"category": "Transport"},
        {"category": "Groceries"},
        {"category": "Transport"},
    ]
    assert present_categories(transactions) == ["Groceries", "Transport"]


def test_present_categories_ignores_missing_category():
    transactions = [{"category": "Groceries"}, {"category": None}, {}]
    assert present_categories(transactions) == ["Groceries"]


def test_present_categories_includes_income():
    # GET /summary's by_category deliberately excludes Income (it's a separate KPI, not spend) —
    # but this helper works over raw transactions, so Income must still be browsable here.
    transactions = [{"category": "Income"}, {"category": "Groceries"}]
    assert present_categories(transactions) == ["Groceries", "Income"]
