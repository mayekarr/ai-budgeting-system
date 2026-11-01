"""
Fill in `Transaction.raw_bank_category` for rows imported before the column existed.

The bank's own Category column was read at upload but never saved, so it has to be recovered from the
statement files. A row is matched on date + amount + description. Two accounts can hold a row with the
same key (the two legs of a transfer share their wording), so each file is tied to the account most of
its rows match, and only that account's rows take its labels. A row that already has a category is never
overwritten, and a key the file labels two different ways is skipped rather than guessed.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable, Mapping

from sqlalchemy.orm import Session

from backend.models import Transaction
from ingestion.nab_format import ParsedRow


def _key(row_date, amount: float, description: str) -> tuple:
    return (row_date, round(amount, 2), description)


def backfill_bank_category(session: Session, files: Mapping[str, Iterable[ParsedRow]]) -> int:
    """`files` maps any label (e.g. "JC") to that statement file's parsed rows. Returns rows updated."""
    index: dict[tuple, list[Transaction]] = defaultdict(list)
    for tx in session.query(Transaction):
        index[_key(tx.date, tx.amount, tx.raw_description)].append(tx)

    changed = 0
    for rows in files.values():
        rows = list(rows)
        votes = Counter(
            tx.account_id
            for row in rows
            for tx in index.get(_key(row.date, row.amount, row.raw_description), [])
        )
        if not votes:
            continue
        account_id = votes.most_common(1)[0][0]

        labels: dict[tuple, set[str]] = defaultdict(set)
        for row in rows:
            if row.raw_bank_category:
                labels[_key(row.date, row.amount, row.raw_description)].add(row.raw_bank_category.strip())
        for key, categories in labels.items():
            if len(categories) != 1:
                continue
            category = next(iter(categories))
            for tx in index.get(key, []):
                if tx.account_id == account_id and tx.raw_bank_category is None:
                    tx.raw_bank_category = category
                    changed += 1
    session.flush()
    return changed
