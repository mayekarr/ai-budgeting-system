from __future__ import annotations

"""
Loan movements decided by their text (docs/product-requirements.md FR-9l, which superseded FR-9f/FR-9i):
  - a drawdown or redraw is a credit worded `LOAN PROCEEDS FROM A/C ...` / `REDRAW PROCEEDS FROM A/C ...`;
  - a lump-sum paydown is a debit to one of the user's home loans, worded `... to <name> HL`
    (e.g. `JC to Barkly HL`).

These are only *recognised* here. `categorisation/capital_events.py` files a drawdown as
`Income / Loan Drawdown` and a paydown as `Loans & Finance / Loan Paydown`: borrowed money coming in and
debt being paid down are real flows, kept out of day-to-day totals by the Overview scope switch rather
than hidden as Transfers.

Regular instalments, repayments and interest are deliberately *not* matched: they stay ordinary
`Loan Repayment` / `Loan Interest` expenses (J6's cash-flow view, because they include interest).

The loan's own statement isn't imported, so there is no counterpart row and transfer detection can't
pair these anyway.
"""

import re


_DRAWDOWN_RE = re.compile(r"\b(?:LOAN|REDRAW) PROCEEDS FROM A/C\b", re.IGNORECASE)
# "<own account nickname> to <loan name> HL", e.g. "JC to Barkly HL": a two-letter upper-case
# nickname, "to", one or two alphabetic words, then an upper-case "HL" as a whole word. Anchoring on
# the nickname keeps a payee ("Payment to Mr Smith HL", "TO KMART HL", "TO SHELL HLDG") out.
_PAYDOWN_RE = re.compile(r"\b(?-i:[A-Z]{2})\s+to\s+(?:[A-Za-z]+\s+){1,2}(?-i:HL)\b", re.IGNORECASE)


def is_loan_movement(raw_description: str, amount: float) -> bool:
    if amount > 0:
        return _DRAWDOWN_RE.search(raw_description) is not None
    if amount < 0:
        return _PAYDOWN_RE.search(raw_description) is not None
    return False
