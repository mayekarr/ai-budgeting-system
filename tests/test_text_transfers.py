from __future__ import annotations

import pytest

from transfers.text_transfers import is_text_only_transfer


@pytest.mark.parametrize("description, amount", [
    ("LOAN PROCEEDS FROM A/C 34-188-5257", 900000.0),                 # loan drawdown
    ("ONLINE N8131366871 JC to Barkly HL MAYEKAR A", -582076.0),      # lump-sum paydown
    ("30774608 0003 MLC MKIS Rohan & Anila Ma", -750.0),              # share contribution
])
def test_text_alone_makes_these_transfers(description, amount):
    assert is_text_only_transfer(description, amount) is True


@pytest.mark.parametrize("description, amount", [
    ("30774608 0097 MLC MKIS CREDITS Rohan & Anila Ma", 284903.24),
    ("LOAN INSTALMENT TO A/C 399934242 MAYEKAR", -244.89),
    ("DIRECT DEBIT PAYMENT", 100.0),    # a card payment waits for detection first, so not here
    ("WOOLWORTHS", -12.0),
])
def test_everything_else_is_not(description, amount):
    assert is_text_only_transfer(description, amount) is False
