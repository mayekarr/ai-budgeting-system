from __future__ import annotations

import pytest

from transfers.investment_contributions import is_investment_contribution


@pytest.mark.parametrize("description, amount", [
    ("30774608 0003 MLC MKIS Rohan & Anila Ma", -750.0),
    ("30774608 0097 mlc mkis rohan & anila ma", -750.0),
    ("30774608 0003 MLC  MKIS Rohan & Anila Ma", -750.0),    # doubled space in the export
    ("30774608 0003 MLC\tMKIS Rohan & Anila Ma", -750.0),
])
def test_periodic_contribution_to_the_share_portfolio_is_recognised(description, amount):
    assert is_investment_contribution(description, amount) is True


@pytest.mark.parametrize("description, amount", [
    # The 2022-04-19 sale payout: a credit, and worded CREDITS. It is real income.
    ("30774608 0097 MLC MKIS CREDITS Rohan & Anila Ma", 284903.24),
    ("30774608 0097 MLC MKIS CREDITS Rohan & Anila Ma", -10.0),
    ("30774608 0097 MLC MKIS CREDIT Rohan & Anila Ma", -10.0),
    ("30774608 0097 MLC  MKIS  CREDITS Rohan & Anila Ma", -10.0),
    ("30774608 0003 MLC MKIS Rohan & Anila Ma", 750.0),
    ("MLC LIMITED DOCKLANDS", -325.47),          # insurance premiums are ordinary spending
    ("BPAY MLC Super 5088723914", -10000.0),
])
def test_payouts_premiums_and_other_mlc_rows_are_not_contributions(description, amount):
    assert is_investment_contribution(description, amount) is False
