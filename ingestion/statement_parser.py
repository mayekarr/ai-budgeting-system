"""
Picks the parser for an uploaded statement from its header row, so `/transactions/upload` takes
every account's export without the caller saying which bank it is. A Macquarie export has separate
`Debit` and `Credit` columns; a NAB-style export has a single `Amount`.
"""

from __future__ import annotations


from ingestion.macquarie_format import parse_macquarie_dataframe
from ingestion.nab_format import NabFormatError, ParseResult, parse_nab_dataframe, read_dataframe


def parse_statement_with_report(raw_bytes: bytes, *, filename: str) -> ParseResult:
    df = read_dataframe(raw_bytes, filename)   # read once; the chosen parser works on this same frame
    columns = {str(c).strip().lower() for c in df.columns}
    if {"debit", "credit"} <= columns:
        return parse_macquarie_dataframe(df)
    if "amount" in columns:
        return parse_nab_dataframe(df)
    raise NabFormatError(
        f"Unrecognised statement layout in {filename}: expected a NAB-style export (an Amount column) "
        "or a Macquarie export (Debit and Credit columns)."
    )
