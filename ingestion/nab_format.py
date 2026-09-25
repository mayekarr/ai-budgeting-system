from __future__ import annotations

"""
Parser for the NAB-style raw export shape (confirmed real layout, §4.1), shared by the CC, JC, RC,
and AC accounts:

    Date, Amount, Account Number, Transaction Type, Transaction Details, Balance,
    Category, Merchant Name, Processed On

`Category`/`Merchant Name` are the bank's own values. `Category` is read as a refund-detection
signal (transfers/refunds.py) and, since 2026-09-25, as a categorisation signal too — via a small
curated mapping (categorisation/bank_category.py) that deliberately excludes the transfer/refund-
labelled values §4.1 found unreliable *for that narrower purpose* (a real invoice mislabelled
"Transfers out"), so that finding isn't reintroduced. `Merchant Name` is stored on
`Transaction.merchant` for display. Classification itself is still decided by
categorisation/rules.py first, this bank-category mapping second, then claude_fallback.py last.
"""

import io
from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd

REQUIRED_COLUMNS = {"date", "amount", "account number", "transaction type", "transaction details", "balance"}


class NabFormatError(Exception):
    """Raised when a file doesn't match the expected NAB-style shape or contains malformed rows."""


@dataclass
class ParsedRow:
    date: date
    amount: float
    account_identifier: str
    raw_transaction_type: str
    raw_description: str
    balance: Optional[float]
    # The bank's own "Category" column, if present — read as a refund-detection signal
    # (transfers/refunds.py) and, via a small curated mapping (categorisation/bank_category.py),
    # as a categorisation signal too. §4.1 found bank-assigned categories demonstrably unreliable
    # specifically as a *transfer/refund type* signal (e.g. a real invoice labelled "Transfers
    # out") -- that finding doesn't mean the value is meaningless for general spend/income
    # categorisation, which is a different question; the mapping deliberately excludes exactly the
    # transfer/refund-labelled values §4.1 is about.
    raw_bank_category: Optional[str] = None
    # The bank's own "Merchant Name" column, if present -- stored on Transaction.merchant for
    # display only (/code-review finding: an earlier version of this comment wrongly claimed it
    # was also consulted by categorisation/bank_category.py -- categorise_from_bank_category() only
    # ever reads raw_bank_category, never this field).
    raw_merchant: Optional[str] = None


def _read_dataframe(raw_bytes: bytes, filename: str) -> pd.DataFrame:
    buffer = io.BytesIO(raw_bytes)
    lower = filename.lower()
    try:
        if lower.endswith((".xlsx", ".xls")):
            return pd.read_excel(buffer)
        return pd.read_csv(buffer)
    except Exception as exc:  # pylint: disable=broad-except
        raise NabFormatError(f"Unable to read {filename} as a NAB-style export: {exc}") from exc


def _require_text(raw, lower_cols: dict, column: str, row_num: int) -> str:
    """
    Read a required text field, raising rather than silently accepting a blank cell as the literal
    string "nan" — pandas represents a blank cell as NaN, and `str(NaN)` stringifies to "nan",
    which is a plausible-looking but wrong value that would otherwise pass through unnoticed (the
    old ingestion/csv_importer.py explicitly skipped blank-description rows; this restores an
    equivalent guard, but as a surfaced error per FR-4 rather than a silent skip).
    """
    val = raw[lower_cols[column]]
    if pd.isna(val) or not str(val).strip():
        raise NabFormatError(f"Row {row_num}: missing required value for {column!r}")
    return str(val).strip()


def parse_nab_format(raw_bytes: bytes, *, filename: str) -> list[ParsedRow]:
    """Parse a NAB-style statement export into a list of normalized rows."""
    df = _read_dataframe(raw_bytes, filename)
    df.columns = [str(c).strip() for c in df.columns]
    lower_cols = {c.lower(): c for c in df.columns}

    missing = REQUIRED_COLUMNS - set(lower_cols.keys())
    if missing:
        raise NabFormatError(f"Missing required column(s) for NAB-style format: {sorted(missing)}")

    rows: list[ParsedRow] = []
    for idx, raw in df.iterrows():
        row_num = idx + 2  # 1-indexed + header row, for a human-facing error message
        try:
            parsed_date = pd.to_datetime(raw[lower_cols["date"]]).date()
        except Exception as exc:  # pylint: disable=broad-except
            raise NabFormatError(f"Row {row_num}: invalid date {raw[lower_cols['date']]!r}") from exc

        try:
            amount = float(raw[lower_cols["amount"]])
        except (TypeError, ValueError) as exc:
            raise NabFormatError(f"Row {row_num}: invalid amount {raw[lower_cols['amount']]!r}") from exc

        account_identifier = _require_text(raw, lower_cols, "account number", row_num)
        raw_transaction_type = _require_text(raw, lower_cols, "transaction type", row_num)
        raw_description = _require_text(raw, lower_cols, "transaction details", row_num)

        balance_val = raw[lower_cols["balance"]]
        balance = None if pd.isna(balance_val) else float(balance_val)

        raw_bank_category = None
        if "category" in lower_cols:
            cat_val = raw[lower_cols["category"]]
            raw_bank_category = None if pd.isna(cat_val) else str(cat_val).strip()

        raw_merchant = None
        if "merchant name" in lower_cols:
            merchant_val = raw[lower_cols["merchant name"]]
            raw_merchant = None if pd.isna(merchant_val) else str(merchant_val).strip()

        rows.append(
            ParsedRow(
                date=parsed_date,
                amount=amount,
                account_identifier=account_identifier,
                raw_transaction_type=raw_transaction_type,
                raw_description=raw_description,
                balance=balance,
                raw_bank_category=raw_bank_category,
                raw_merchant=raw_merchant,
            )
        )

    return rows
