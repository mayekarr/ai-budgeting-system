from __future__ import annotations

import pytest

from transfers.loan_movements import is_loan_movement


@pytest.mark.parametrize(
    "description, amount",
    [
        ("LOAN PROCEEDS FROM A/C 34-188-5257", 900000.00),
        ("LOAN PROCEEDS FROM A/C 34-189-2465", 63014.45),
        ("REDRAW PROCEEDS FROM A/C 70-320-6283", 47000.00),
        ("redraw proceeds from a/c 70-320-6283", 7000.00),
        ("ONLINE N8131366871 JC to Barkly HL MAYEKAR A", -582076.00),
        ("ONLINE R2219386106 JC to Barkly HL MAYEKAR A", -33900.00),
        ("ONLINE R2219386107 AC to Hillside Crescent HL MAYEKAR A", -10000.00),
    ],
)
def test_drawdowns_redraws_and_lump_sum_paydowns_are_loan_movements(description, amount):
    assert is_loan_movement(description, amount) is True


@pytest.mark.parametrize(
    "description, amount",
    [
        # Regular instalments, repayments and interest stay Expense (J6's cash-flow view).
        ("LOAN INSTALMENT TO A/C 399934242 MAYEKAR", -244.89),
        ("LOAN REPAYMENT TO A/C 703206283 MAYEKAR A", -6489.89),
        ("INTEREST CHARGED FROM A/C 34-188-5257", -4877.79),
        ("INTERNET TRANSFER Ex Loan Repayment Rohan Mayekar", -1000.00),
        ("ONLINE K1111111111 Month ex loanrepay MAYEKAR A", -1000.00),
        # Ordinary spending.
        ("WOOLWORTHS 3150 FOREST HILL", -35.45),
        ("PAYMENT TO SHELL HLDG PTY LTD", -80.00),
        # Too loose to trust: lower-case "hl" and digit-only words are not a home-loan name.
        ("Payment to J Smith hl", -50.00),
        ("Transfer to 12345 HL", -100.00),
        # A paydown is written "<own account nickname> to <loan name> HL", never a payee's name.
        ("Payment to Mr Smith HL", -250.00),
        ("Transfer to Kmart HL", -90.00),
        ("PAYMENT TO KMART HL", -90.00),
    ],
)
def test_instalments_interest_and_ordinary_rows_are_not_loan_movements(description, amount):
    assert is_loan_movement(description, amount) is False


def test_sign_must_match_the_kind_of_movement():
    # Money coming out of a loan is a credit; a paydown is a debit.
    assert is_loan_movement("LOAN PROCEEDS FROM A/C 34-188-5257", -900000.00) is False
    assert is_loan_movement("ONLINE N8131366871 JC to Barkly HL MAYEKAR A", 582076.00) is False
