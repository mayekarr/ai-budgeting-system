"""
Picks the parser for an uploaded statement from its header row, so `/transactions/upload` takes
every account's export without the caller saying which bank it is. A Macquarie export has separate
`Debit` and `Credit` columns; a NAB-style export has a single `Amount`; a headerless CommBank export has no
header at all, which shows as a date and a number where the column names should be.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from ingestion.commbank_format import parse_commbank_dataframe
from ingestion.macquarie_format import parse_macquarie_dataframe
from ingestion.nab_format import NabFormatError, ParseResult, parse_nab_dataframe, read_dataframe


def _looks_like_data(label_date, label_amount) -> bool:
    """True when the first two 'column names' are really a date and a number: the file has no header row."""
    try:
        pd.Timestamp(label_date)
        float(label_amount)
    except (TypeError, ValueError):
        return False
    return True


def parse_statement_with_report(raw_bytes: bytes, *, filename: str, account: Optional[str] = None) -> ParseResult:
    """
    `account` names the account for a file that does not say (the headerless NBA export); it is ignored for
    a file that does, and required for one that does not.
    """
    df = read_dataframe(raw_bytes, filename)   # read once; the chosen parser works on this same frame
    if len(df.columns) >= 2 and _looks_like_data(df.columns[0], df.columns[1]):
        if account is None or not account.strip():
            raise NabFormatError(
                f"{filename} has no header row and names no account: upload it with the `account` parameter "
                "(the account's name or alias, for example the NBA account)."
            )
        return parse_commbank_dataframe(read_dataframe(raw_bytes, filename, header=None), account.strip())
    columns = {str(c).strip().lower() for c in df.columns}
    if {"debit", "credit"} <= columns:
        return parse_macquarie_dataframe(df)
    if "amount" in columns:
        return parse_nab_dataframe(df)
    raise NabFormatError(
        f"Unrecognised statement layout in {filename}: expected a NAB-style export (an Amount column), "
        "a Macquarie export (Debit and Credit columns) or a headerless CommBank export (date, amount, "
        "description, balance)."
    )
