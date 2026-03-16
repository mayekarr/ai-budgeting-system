from __future__ import annotations

from io import StringIO

from ingestion.csv_importer import ImportedTransaction, load_transactions


def test_load_transactions_basic():
    csv_content = """Date,Description,Amount
2026-01-05,UBER TRIP,-22.40
2026-01-06,WOOLWORTHS,-85.20
2026-01-08,NETFLIX,-15.99
"""
    buffer = StringIO(csv_content)

    transactions = load_transactions(buffer)

    assert isinstance(transactions, list)
    assert len(transactions) == 3

    first: ImportedTransaction = transactions[0]
    assert str(first.date) == "2026-01-05"
    assert first.description == "UBER TRIP"
    assert first.amount == -22.40

    last: ImportedTransaction = transactions[-1]
    assert last.description == "NETFLIX"
    assert last.amount == -15.99

