"""
Parser for the Macquarie export shape, shared by the MAC (Cash Management Account) and MACACC
(Cash Management Accelerator Account) files:

    Transaction Date, Details, Account, Category, Subcategory, Tags, Notes, Debit, Credit, Balance,
    Original Description

It differs from the NAB-style export (ingestion/nab_format.py) in four ways, each handled here:

- Money is in two columns: `Debit` and `Credit`. The amount is credit minus debit.
- There is no account number. The `Account` column holds the account's *name*, which is the only
  identifier the file gives, so that name is what an `AccountAlias` is registered against.
- There is no bank transaction type. One is derived from Macquarie's `Subcategory`, using values the
  transfer matcher already understands (transfers/detection.py): interest and dividends can never be
  a transfer leg, and a `Transfers` row is a TRANSFER DEBIT / TRANSFER CREDIT by its sign.
- `Category`/`Subcategory` are Macquarie's own vocabulary ("Financial" / "Transfers"). They are not
  stored as the bank category: Tier-2 pairing rejects any bank category outside NAB's transfer-like
  set, and Macquarie's "Transfers" is not in it, so storing it would wrongly stop every pairing.

`Details` is the readable description and, for a payment out, carries the receipt number, BSB and
account number; `Original Description` is the bank's raw text, truncated for those rows. The richer
`Details` is used, with the original as the fallback.
"""

from __future__ import annotations


from typing import Optional

import pandas as pd

from ingestion.nab_format import NabFormatError, ParsedRow, ParseResult, read_dataframe
from ingestion.seam_repeats import drop_seam_repeats

# "Original Description" is only a fallback for a blank Details, so a file without it still parses.
REQUIRED_COLUMNS = {"transaction date", "details", "account", "debit", "credit", "balance"}

# Macquarie Subcategory -> the bank transaction type the transfer matcher gates on.
# Macquarie Subcategory -> (category, subcategory) for the two kinds of row the file labels unambiguously.
# BPAY payments and direct debits are left unset: the file does not say what they were for.
_HINT_BY_SUBCATEGORY = {
    "interest": ("Income", "Interest"),
    "dividends & distributions": ("Income", "Dividends & Distributions"),
}

_TYPE_BY_SUBCATEGORY = {
    "interest": "INTEREST PAID",
    "dividends & distributions": "DIVIDEND",
    "bpay payments": "BPAY",
    "direct debits": "DIRECT DEBIT",
}


class MacquarieFormatError(NabFormatError):
    """A Macquarie file that is missing columns or has malformed rows.

    A subclass of NabFormatError so the upload route reports it as a 400 with no special case.
    """


def _text(raw, column: str) -> Optional[str]:
    val = raw[column]
    if pd.isna(val) or not str(val).strip():
        return None
    return str(val).strip()


def _money(raw, column: str, row_num: int) -> Optional[float]:
    val = raw[column]
    if pd.isna(val) or (isinstance(val, str) and not val.strip()):
        return None
    try:
        return float(val)
    except (TypeError, ValueError) as exc:
        raise MacquarieFormatError(f"Row {row_num}: invalid {column} {val!r}") from exc


def _bank_type(subcategory: Optional[str], amount: float) -> str:
    mapped = _TYPE_BY_SUBCATEGORY.get((subcategory or "").lower())
    if mapped is not None:
        return mapped
    if (subcategory or "").lower() == "transfers":
        return "TRANSFER CREDIT" if amount > 0 else "TRANSFER DEBIT"
    return ""  # an unmapped kind of row: no bank type, which the matcher allows


def parse_macquarie_format(raw_bytes: bytes, *, filename: str) -> list[ParsedRow]:
    """Parse a Macquarie statement export into a list of normalised rows."""
    return parse_macquarie_format_with_report(raw_bytes, filename=filename).rows


def parse_macquarie_format_with_report(raw_bytes: bytes, *, filename: str) -> ParseResult:
    """Like `parse_macquarie_format`, but also reports how many seam-repeat and $0 rows were left out."""
    return parse_macquarie_dataframe(read_dataframe(raw_bytes, filename))


def parse_macquarie_dataframe(df: pd.DataFrame) -> ParseResult:
    """The Macquarie parser on an already-read file, so a caller that sniffed the layout does not read it twice."""
    df.columns = [str(c).strip().lower() for c in df.columns]

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise MacquarieFormatError(f"Missing required column(s) for Macquarie format: {sorted(missing)}")

    rows: list[ParsedRow] = []
    for idx, raw in df.iterrows():
        row_num = idx + 2  # 1-indexed + header row, for a human-facing error message
        try:
            parsed_date = pd.to_datetime(raw["transaction date"]).date()
        except Exception as exc:  # pylint: disable=broad-except
            raise MacquarieFormatError(f"Row {row_num}: invalid date {raw['transaction date']!r}") from exc

        debit = _money(raw, "debit", row_num)
        credit = _money(raw, "credit", row_num)
        if (debit is None) == (credit is None):
            raise MacquarieFormatError(f"Row {row_num}: expected exactly one of Debit and Credit, got {debit!r} and {credit!r}")
        if (debit is not None and debit < 0) or (credit is not None and credit < 0):
            # Both columns hold magnitudes; a negative one would silently flip the row's sign.
            raise MacquarieFormatError(f"Row {row_num}: negative Debit or Credit ({debit!r}, {credit!r})")
        amount = credit if credit is not None else -debit

        account = _text(raw, "account")
        description = _text(raw, "details") or (
            _text(raw, "original description") if "original description" in df.columns else None
        )
        if account is None or description is None:
            raise MacquarieFormatError(f"Row {row_num}: missing required value for 'account' or 'details'")

        balance_val = raw["balance"]
        balance = None if pd.isna(balance_val) else float(balance_val)

        subcategory = _text(raw, "subcategory") if "subcategory" in df.columns else None
        rows.append(
            ParsedRow(
                date=parsed_date,
                amount=amount,
                account_identifier=account,
                raw_transaction_type=_bank_type(subcategory, amount),
                raw_description=description,
                balance=balance,
                category_hint=_HINT_BY_SUBCATEGORY.get((subcategory or "").lower()),
            )
        )

    # Same page-seam duplication guard as the NAB export (FR-9k); it only acts on a long identical block at
    # a date-order break, so it leaves a short Macquarie file alone.
    kept, dropped = drop_seam_repeats(rows)
    non_zero = [r for r in kept if r.amount != 0]
    return ParseResult(
        rows=non_zero, seam_repeats_dropped=len(dropped), zero_amount_skipped=len(kept) - len(non_zero),
        institution="Macquarie",
    )
