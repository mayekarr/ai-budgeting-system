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


# Dash-insensitive account numbers (2026-10-18): the same loan appears undashed ("703206283") in
# one bank line and dashed ("70-320-6283") in another, so a registered number must match either.

def test_undashed_alias_matches_the_dashed_form_in_text():
    assert alias_matches_text("703206283", "REDRAW PROCEEDS FROM A/C 70-320-6283") is True


def test_dashed_alias_matches_the_undashed_form_in_text():
    assert alias_matches_text("34-188-5257", "LOAN PROCEEDS FROM A/C 341885257") is True


def test_dashed_alias_still_matches_its_own_form():
    assert alias_matches_text("34-188-5257", "INTEREST CHARGED FROM A/C 34-188-5257") is True


def test_dash_insensitive_matching_does_not_match_a_different_number():
    assert alias_matches_text("703206283", "REDRAW PROCEEDS FROM A/C 70-320-6284") is False
    assert alias_matches_text("703206283", "A/C 70-320-628") is False


def test_alias_with_letters_is_not_made_dash_insensitive():
    # Only account-number-like aliases (digits and dashes) get the relaxed matching.
    assert alias_matches_text("AMEX 1234", "AMEX-1234") is False


def test_number_alias_does_not_match_inside_a_longer_digit_run():
    # A loan number must not match part of a longer reference, BSB+account string or amount.
    assert alias_matches_text("703206283", "REF 9703206283") is False
    assert alias_matches_text("703206283", "REF 7032062831") is False
    assert alias_matches_text("34-188-5257", "A/C 134-188-5257") is False
    assert alias_matches_text("34-188-5257", "A/C 34-188-52571") is False


def test_number_alias_still_matches_when_flanked_by_non_digits():
    assert alias_matches_text("703206283", "TO A/C 703206283 MAYEKAR") is True
    assert alias_matches_text("703206283", "A/C703206283X") is True
    assert alias_matches_text("703206283", "70-320-6283") is True


def test_number_alias_with_trailing_whitespace_still_matches():
    # `$` would let an identifier with a trailing newline through the digits-only check and then
    # bake the newline into the pattern, so it could never match. The identifier is stripped first.
    assert alias_matches_text("703206283\n", "TO A/C 703206283 MAYEKAR") is True
    assert alias_matches_text(" 34-188-5257 ", "A/C 341885257") is True
