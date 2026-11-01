"""
Fill in the bank's own Category for rows already in finance.db, from the statement files.

Usage (from the repo root, with the venv active):
    python -m scripts.backfill_bank_category [folder]

`folder` defaults to transaction-files/ and is expected to hold the NAB-format exports named
`BankTransactions - long - <AC|CC|JC|RC>.xlsx`. Idempotent: rows that already have a category are left
alone. Back up finance.db first.
"""

from __future__ import annotations

import sys
from pathlib import Path

from backend.database import create_tables, session_scope
from ingestion.bank_category_backfill import backfill_bank_category
from ingestion.nab_format import parse_nab_format

LABELS = ("AC", "CC", "JC", "RC")


def main(argv: list[str]) -> int:
    folder = Path(argv[1]) if len(argv) > 1 else Path("transaction-files")
    files = {}
    for label in LABELS:
        path = folder / f"BankTransactions - long - {label}.xlsx"
        if not path.exists():
            print(f"Missing {path}; skipping {label}.")
            continue
        files[label] = parse_nab_format(path.read_bytes(), filename=path.name)
    if not files:
        print("No statement files found.")
        return 1
    create_tables()  # also adds any column an older database lacks
    with session_scope() as session:
        changed = backfill_bank_category(session, files)
    print(f"bank category filled in for {changed} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
