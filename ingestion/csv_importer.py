from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from io import BytesIO, StringIO
from typing import IO, Iterable, List, Union

import logging
import pandas as pd


logger = logging.getLogger(__name__)


class CsvImportError(Exception):
    """Raised when a CSV file cannot be parsed into transactions."""


@dataclass
class ImportedTransaction:
    """Simple in-memory representation of an imported transaction."""
    date: date
    description: str
    amount: float


FileLike = Union[str, IO[str], IO[bytes], bytes]


def _to_readable_buffer(file: FileLike) -> Union[StringIO, BytesIO, str]:
    """
    Normalize input into a pandas-readable source.

    Accepts:
        - File path (str)
        - Text IO
        - Binary IO
        - Raw bytes (e.g. FastAPI UploadFile.read())
    """
    if isinstance(file, str):
        logger.debug("CSV importer received file path input.")
        return file

    if isinstance(file, (bytes, bytearray)):
        logger.debug("CSV importer received raw bytes input of length %d.", len(file))
        return BytesIO(file)

    if hasattr(file, "read"):
        logger.debug("CSV importer received file-like object %r.", file)
        file.seek(0)
        data = file.read()
        if isinstance(data, bytes):
            return BytesIO(data)
        return StringIO(str(data))

    logger.debug("CSV importer received buffer object %r.", file)
    return file


def load_transactions(file: FileLike) -> List[ImportedTransaction]:
    """
    Load and normalize transactions from a CSV file.

    Expected columns (case-insensitive):
        - Date
        - Description
        - Amount

    Returns:
        List[ImportedTransaction]

    Raises:
        CsvImportError: if the CSV is invalid or missing required columns.
    """
    buffer = _to_readable_buffer(file)

    try:
        df = pd.read_csv(buffer)
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Failed to read CSV.")
        raise CsvImportError(f"Failed to read CSV: {exc}") from exc

    if df.empty:
        logger.info("CSV importer loaded an empty DataFrame.")
        return []

    # Normalize column names to lowercase for flexible matching.
    df.columns = [str(c).strip().lower() for c in df.columns]

    required_cols = {"date", "description", "amount"}
    if not required_cols.issubset(df.columns):
        missing = required_cols - set(df.columns)
        logger.error("CSV importer missing required columns: %s", ", ".join(sorted(missing)))
        raise CsvImportError(f"Missing required columns: {', '.join(sorted(missing))}")

    # Parse and clean data
    try:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Invalid date format in CSV.")
        raise CsvImportError(f"Invalid date format in CSV: {exc}") from exc

    try:
        df["amount"] = df["amount"].astype(float)
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Invalid amount format in CSV.")
        raise CsvImportError(f"Invalid amount format in CSV: {exc}") from exc

    df["description"] = df["description"].astype(str).fillna("").str.strip()

    transactions: List[ImportedTransaction] = []
    for _, row in df.iterrows():
        # Basic row-level validation
        if not row["description"]:
            # Skip rows without description; these are typically non-transactional.
            continue

        transactions.append(
            ImportedTransaction(
                date=row["date"],
                description=row["description"],
                amount=float(row["amount"]),
            )
        )

    logger.info("CSV importer successfully loaded %d transaction rows.", len(transactions))
    return transactions

