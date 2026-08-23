from __future__ import annotations

"""
Parser for the NAB-style raw export shape (confirmed real layout, §4.1), shared by the CC, JC, RC,
and AC accounts:

    Date, Amount, Account Number, Transaction Type, Transaction Details, Balance,
    Category, Merchant Name, Processed On

`Category`/`Merchant Name` are the bank's own values — read for reference only, never trusted as
the classification output (§4.1's own finding: demonstrably unreliable for transfer/category
purposes). The real classification comes from categorisation/rules.py + claude_fallback.py.
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
    # The bank's own "Category" column, if present — read only as a refund/transfer *detection
    # signal* (transfers/refunds.py, transfers/detection.py), never as the transaction's actual
    # category. §4.1 found bank-assigned categories demonstrably unreliable for classification.
    raw_bank_category: Optional[str] = None


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

        rows.append(
            ParsedRow(
                date=parsed_date,
                amount=amount,
                account_identifier=account_identifier,
                raw_transaction_type=raw_transaction_type,
                raw_description=raw_description,
                balance=balance,
                raw_bank_category=raw_bank_category,
            )
        )

    return rows
