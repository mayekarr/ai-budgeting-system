"""
Parser for the headerless CommBank-style export (the NBA account, which receives Rohan's payroll and
forwards a fixed tranche to RC). Four columns and no header row:

    date, amount (signed), description, balance

Newest row first. It differs from the NAB and Macquarie exports in what it lacks, and each gap is handled
here:

- There is no header row, so the first line is data. The dispatcher (ingestion/statement_parser.py) spots
  the layout and reads the file with `header=None`.
- There is no account column or number, so the caller supplies the account's name or alias (the upload's
  `account` parameter) and it is used as the identifier.
- There is no bank transaction type or category. A type is derived from the description with values the
  transfer matcher already understands: a salary or dividend credit, a card purchase and a refund are never
  transfer legs, and a `Transfer To/From ...` row is a TRANSFER DEBIT/CREDIT by its sign. A bank category is
  not saved, since the rebuild guard and Tier-2 pairing both treat a missing one as allowed.
- Salary and dividend rows carry a category hint, so they are not left for the unavailable LLM.
"""

from __future__ import annotations

import re
from typing import Optional

import pandas as pd

from ingestion.nab_format import NabFormatError, ParsedRow, ParseResult
from ingestion.seam_repeats import drop_seam_repeats

_COLUMNS = ["date", "amount", "description", "balance"]

_YEAR_FIRST_RE = re.compile(r"^\s*\d{4}\D")   # 2026/09/05 is year-month-day; day-first would swap month and day
_SALARY_RE = re.compile(r"^\s*Salary\b", re.IGNORECASE)
_DIVIDEND_RE = re.compile(r"\bDIV\b|\bDIVIDEND\b", re.IGNORECASE)
_REFUND_RE = re.compile(r"^\s*Refund\b", re.IGNORECASE)
_TRANSFER_RE = re.compile(r"^\s*(?:Fast\s+)?Transfer\s+(?:to|from)\b", re.IGNORECASE)
# xx2801 is Rohan's travel account (2026-11-03). Its statements are not imported, so money moved into it is
# spending and money back out of it nets against that spending; neither is a transfer leg. Personal
# constant: edit for a different household.
_TRAVEL_ACCOUNT_RE = re.compile(r"^\s*Transfer\s+(?:to|from)\s+xx2801\b", re.IGNORECASE)
_TRAVEL_HINT = ("Travel & Holidays", "Other")


class CommbankFormatError(NabFormatError):
    """A headerless CommBank file with the wrong shape or a malformed row.

    A subclass of NabFormatError so the upload route reports it as a 400 with no special case.
    """


def _to_date(value):
    """A real date as is; a text date with slashes is dd/mm/yyyy (CommBank's CSV), never month-first."""
    if isinstance(value, str) and "/" in value and not _YEAR_FIRST_RE.match(value):
        return pd.to_datetime(value, dayfirst=True).date()
    return pd.to_datetime(value).date()


def _bank_type(description: str, amount: float) -> str:
    if _TRAVEL_ACCOUNT_RE.search(description):
        return "DEPOSIT" if amount > 0 else "PURCHASE AUTHORISATION"   # never a transfer leg
    if amount > 0 and _SALARY_RE.search(description):
        return "SALARY"
    if amount > 0 and _DIVIDEND_RE.search(description):
        return "DIVIDEND"
    if amount > 0 and _REFUND_RE.search(description):
        return "CREDIT CARD REFUND"
    if _TRANSFER_RE.search(description):
        return "TRANSFER CREDIT" if amount > 0 else "TRANSFER DEBIT"
    if amount < 0:
        return "PURCHASE AUTHORISATION"   # any other payment out: never a transfer leg
    return ""                             # an unlabelled credit: no bank type, which the matcher allows


def _category_hint(bank_type: str, description: str) -> Optional[tuple[str, Optional[str]]]:
    if _TRAVEL_ACCOUNT_RE.search(description):
        return _TRAVEL_HINT
    if bank_type == "SALARY":
        return ("Income", "Salary")
    if bank_type == "DIVIDEND":
        return ("Income", "Dividends & Distributions")
    return None


def parse_commbank_dataframe(df: pd.DataFrame, account_identifier: str) -> ParseResult:
    """Parse a headerless CommBank statement (already read with `header=None`) for the named account."""
    if df.shape[1] != len(_COLUMNS):
        raise CommbankFormatError(
            f"Expected {len(_COLUMNS)} columns (date, amount, description, balance), found {df.shape[1]}."
        )
    df = df.copy()
    df.columns = _COLUMNS

    rows: list[ParsedRow] = []
    for idx, raw in df.iterrows():
        row_num = idx + 1  # 1-indexed; there is no header row to skip
        try:
            parsed_date = _to_date(raw["date"])
        except Exception as exc:  # pylint: disable=broad-except
            raise CommbankFormatError(f"Row {row_num}: invalid date {raw['date']!r}") from exc
        try:
            amount = float(raw["amount"])
        except (TypeError, ValueError) as exc:
            raise CommbankFormatError(f"Row {row_num}: invalid amount {raw['amount']!r}") from exc

        description = None if pd.isna(raw["description"]) else str(raw["description"]).strip()
        if not description:
            raise CommbankFormatError(f"Row {row_num}: missing description")

        balance = None if pd.isna(raw["balance"]) else float(raw["balance"])
        bank_type = _bank_type(description, amount)
        rows.append(
            ParsedRow(
                date=parsed_date,
                amount=amount,
                account_identifier=account_identifier,
                raw_transaction_type=bank_type,
                raw_description=description,
                balance=balance,
                category_hint=_category_hint(bank_type, description),
            )
        )

    kept, dropped = drop_seam_repeats(rows)
    non_zero = [r for r in kept if r.amount != 0]
    return ParseResult(
        rows=non_zero, seam_repeats_dropped=len(dropped), zero_amount_skipped=len(kept) - len(non_zero),
        institution="CommBank",
    )
