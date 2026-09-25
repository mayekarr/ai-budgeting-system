from __future__ import annotations

from categorisation.bank_category import categorise_from_bank_category
from categorisation.taxonomy import is_valid_category


def test_maps_a_representative_sample_of_real_bank_categories():
    # Real values observed across all 4 real, currently-supported account files
    # (transaction-files/) -- see docs/next-steps.md for the full quantified finding (409/422 real
    # rows carry a non-blank bank Category).
    cases = {
        "Groceries": ("Groceries", None),
        "Restaurants & takeaway": ("Cafes & Restaurants", "Restaurants & Takeaway"),
        "Cafe & coffee": ("Cafes & Restaurants", "Cafes & Coffee"),
        "Donations": ("Gifts & Donations", "Donations"),
        "Gifts": ("Gifts & Donations", "Gifts"),
        "Gym & fitness": ("Health & Medical", "Gym & Fitness"),
        "Insurance": ("Insurance", None),
        "Taxis & ride shares": ("Transport", "Taxis & Rideshare"),
        "Medical": ("Health & Medical", "Medical"),
        "Public transport": ("Transport", "Public Transport"),
        "Accommodation": ("Travel & Holidays", "Accommodation"),
        "Utilities": ("Housing", "Utility Bills"),
        "Flights": ("Travel & Holidays", "Flights"),
        "Phone & internet": ("Services & Subscriptions", "Phone & Internet"),
        "Parking & tolls": ("Transport", "Parking & Tolls"),
        "Electronics & technology": ("Shopping", "Electronics & Technology"),
        "Homeware": ("Shopping", "Homeware"),
        "Government": ("Government & Tax", "Government Fees"),
        "Media": ("Services & Subscriptions", "Media/Streaming"),
        "Attractions & events": ("Travel & Holidays", "Attractions & Events"),
    }
    for bank_category, expected in cases.items():
        result = categorise_from_bank_category(bank_category)
        assert result == expected, bank_category
        # Every mapped pair must actually be a valid taxonomy pairing, not just plausible-looking.
        assert is_valid_category(*expected), bank_category


def test_matches_case_insensitively():
    assert categorise_from_bank_category("groceries") == ("Groceries", None)
    assert categorise_from_bank_category("GROCERIES") == ("Groceries", None)


def test_never_maps_transfer_or_refund_labelled_categories():
    # The exact §4.1 finding this whole module exists alongside, not despite: these bank category
    # values are demonstrably unreliable as a transfer/refund *type* signal (real invoices/
    # payments mislabelled), so they must never drive a spend/income category assignment either --
    # a wrong Transfer/Refund label could otherwise mask a real Miscellaneous-worthy transaction as
    # confidently something else.
    for unreliable in (
        "Internal transfers", "Transfers out", "Transfers in", "Refund", "Credit card repayments",
    ):
        assert categorise_from_bank_category(unreliable) is None, unreliable


def test_unrecognised_or_blank_category_returns_none():
    assert categorise_from_bank_category("Uncategorised") is None
    assert categorise_from_bank_category(None) is None
    assert categorise_from_bank_category("") is None
    assert categorise_from_bank_category("Some Brand New Bank Category Never Seen Before") is None
