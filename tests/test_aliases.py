from __future__ import annotations

from transfers.aliases import alias_matches_text


def test_masked_alias_matches_real_unmasked_digits():
    assert alias_matches_text("453030xxxxxx7128", "4530307001277128 NAB CARD AUTOPAY") is True


def test_incidental_single_x_is_not_treated_as_masking():
    assert alias_matches_text("AMEX 1234", "AM SOMETHING ELSE 1234 UNRELATED") is False
    assert alias_matches_text("AMEX 1234", "payment to AMEX 1234 card") is True


def test_alias_consisting_only_of_masking_characters_matches_nothing():
    # Zero identifying signal — must never degenerate into a wildcard that matches every string.
    assert alias_matches_text("xxxxxx", "literally any text at all") is False
    assert alias_matches_text("xxxxxx", "") is False


def test_plain_numeric_alias_matches_literally():
    assert alias_matches_text("133500607", "some text 133500607 more text") is True
    assert alias_matches_text("133500607", "unrelated") is False
