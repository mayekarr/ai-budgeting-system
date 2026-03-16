from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, Iterable, Mapping, Optional

import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, Transaction

logger = logging.getLogger(__name__)

SQLALCHEMY_DATABASE_URL = "sqlite:///finance.db"

# For SQLite, check_same_thread must be False when used with FastAPI / threaded servers.
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_tables() -> None:
    """Create database tables if they do not already exist."""
    logger.info("Creating database tables if they do not exist.")
    Base.metadata.create_all(bind=engine)


def get_session() -> Generator[Session, None, None]:
    """
    FastAPI dependency-style session generator.

    Usage:
        Depends(get_session)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """
    Context manager for a transactional session.

    Example:
        with session_scope() as session:
            ...
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def save_transaction(
    session: Session,
    *,
    date,
    description: str,
    merchant: Optional[str],
    amount: float,
    category: Optional[str],
) -> Transaction:
    """
    Persist a single transaction to the database.

    Parameters mirror the Transaction model fields (excluding id).
    """
    tx = Transaction(
        date=date,
        description=description,
        merchant=merchant,
        amount=amount,
        category=category,
    )
    session.add(tx)
    logger.debug(
        "Queued transaction for save: date=%s, merchant=%s, amount=%s, category=%s",
        date,
        merchant,
        amount,
        category,
    )
    return tx


def bulk_save_transactions(
    session: Session,
    transactions: Iterable[Mapping],
) -> None:
    """
    Bulk-save multiple transaction-like mappings.

    Each mapping should contain keys: date, description, merchant, amount, category.
    """
    count = 0
    for t in transactions:
        save_transaction(
            session,
            date=t["date"],
            description=t["description"],
            merchant=t.get("merchant"),
            amount=t["amount"],
            category=t.get("category"),
        )
        count += 1
    logger.info("Queued %d transactions for bulk save.", count)

