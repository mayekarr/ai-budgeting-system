from __future__ import annotations

"""
Shared helpers for end-to-end tests.
"""

from backend.database import SessionLocal, create_tables
from backend.models import Transaction


def reset_transactions_table() -> None:
    """
    Ensure the transactions table exists and is empty for a clean end-to-end run.

    Note: Uses the default finance.db URL; running these tests will clear the
    transactions table in that database.
    """
    create_tables()
    session = SessionLocal()
    try:
        session.query(Transaction).delete()
        session.commit()
    finally:
        session.close()

