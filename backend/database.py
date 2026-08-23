from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from typing import Generator, Iterable, List, Mapping, Optional

import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, Transaction

logger = logging.getLogger(__name__)

# NAB-format pending/settled transaction-type vocabulary (§4.1). A settlement can land under a
# different date than its authorization, so these are reconciled separately from _is_duplicate's
# exact-date match, not folded into it.
_PENDING_TRANSACTION_TYPES = {"PURCHASE AUTHORISATION"}
_SETTLED_TRANSACTION_TYPES = {"CREDIT CARD PURCHASE"}
_SETTLEMENT_WINDOW = timedelta(days=10)

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


def _is_duplicate(
    session: Session, account_id: int, date, amount: float, raw_description: str, balance: Optional[float]
) -> bool:
    """
    FR-3: re-uploading an overlapping statement must not duplicate transactions.

    A transaction is considered a duplicate of an existing row on the same account, date, amount,
    raw description, and balance — the fields a bank export reliably repeats verbatim across
    overlapping statement periods. `balance` disambiguates two genuinely different same-day
    transactions that otherwise share amount/description (e.g. two identical coffees at the same
    cafe) — their running balance differs even though nothing else does.
    """
    existing = (
        session.query(Transaction.id)
        .filter(
            Transaction.account_id == account_id,
            Transaction.date == date,
            Transaction.amount == amount,
            Transaction.raw_description == raw_description,
            Transaction.balance == balance,
        )
        .first()
    )
    return existing is not None


def _closest_by_date(candidates: List[Transaction], target_date) -> Optional[Transaction]:
    """
    When more than one candidate matches, the closest date is almost always the true pair —
    picking an arbitrary one (e.g. whatever the DB returns first) risks resolving the wrong row
    while leaving the true match still counted as active. Mirrors
    transfers/detection.py's identical reasoning for the analogous transfer-matching ambiguity.
    """
    if not candidates:
        return None
    return min(candidates, key=lambda c: abs((c.date - target_date).days))


def _find_pending_counterpart(
    session: Session, account_id: int, date, amount: float, raw_description: str
) -> Optional[Transaction]:
    """Find an existing, not-yet-superseded PENDING row this SETTLED row resolves."""
    window_start = date - _SETTLEMENT_WINDOW
    window_end = date + _SETTLEMENT_WINDOW
    candidates = (
        session.query(Transaction)
        .filter(
            Transaction.account_id == account_id,
            Transaction.amount == amount,
            Transaction.raw_description == raw_description,
            Transaction.raw_transaction_type.in_(_PENDING_TRANSACTION_TYPES),
            Transaction.superseded_by_id.is_(None),
            Transaction.date >= window_start,
            Transaction.date <= window_end,
        )
        .all()
    )
    return _closest_by_date(candidates, date)


def _find_settled_counterpart(
    session: Session, account_id: int, date, amount: float, raw_description: str
) -> Optional[Transaction]:
    """Find an existing SETTLED row that already resolves this (out-of-order) PENDING row."""
    window_start = date - _SETTLEMENT_WINDOW
    window_end = date + _SETTLEMENT_WINDOW
    candidates = (
        session.query(Transaction)
        .filter(
            Transaction.account_id == account_id,
            Transaction.amount == amount,
            Transaction.raw_description == raw_description,
            Transaction.raw_transaction_type.in_(_SETTLED_TRANSACTION_TYPES),
            Transaction.date >= window_start,
            Transaction.date <= window_end,
        )
        .all()
    )
    return _closest_by_date(candidates, date)


def save_transaction(
    session: Session,
    *,
    account_id: int,
    date,
    amount: float,
    raw_description: str,
    merchant: Optional[str] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    type: str = "Expense",
    is_refund: bool = False,
    transfer_group_id: Optional[int] = None,
    source: str = "bank_import",
    needs_review: bool = False,
    confidence_score: Optional[float] = None,
    raw_transaction_type: Optional[str] = None,
    balance: Optional[float] = None,
) -> Optional[Transaction]:
    """
    Persist a single transaction, skipping it if it's a duplicate of an existing row (FR-3), and
    reconciling a pending<->settled pair (§4.1) if this row is either side of one.

    Returns the created Transaction, or None if the row was a duplicate and skipped.
    """
    if _is_duplicate(session, account_id, date, amount, raw_description, balance):
        logger.debug("Skipping duplicate transaction: account_id=%s date=%s amount=%s", account_id, date, amount)
        return None

    superseded_by_id = None
    if raw_transaction_type in _PENDING_TRANSACTION_TYPES:
        settled = _find_settled_counterpart(session, account_id, date, amount, raw_description)
        if settled is not None:
            superseded_by_id = settled.id

    tx = Transaction(
        account_id=account_id,
        date=date,
        amount=amount,
        raw_description=raw_description,
        merchant=merchant,
        category=category,
        subcategory=subcategory,
        type=type,
        is_refund=is_refund,
        transfer_group_id=transfer_group_id,
        source=source,
        needs_review=needs_review,
        confidence_score=confidence_score,
        raw_transaction_type=raw_transaction_type,
        balance=balance,
        superseded_by_id=superseded_by_id,
    )
    session.add(tx)
    session.flush()  # assign tx.id, needed below and by callers linking against it immediately

    if raw_transaction_type in _SETTLED_TRANSACTION_TYPES:
        pending = _find_pending_counterpart(session, account_id, date, amount, raw_description)
        if pending is not None:
            pending.superseded_by_id = tx.id

    logger.debug("Queued transaction for save: date=%s, merchant=%s, amount=%s, category=%s", date, merchant, amount, category)
    return tx


def bulk_save_transactions(session: Session, transactions: Iterable[Mapping]) -> List[Transaction]:
    """
    Bulk-save multiple transaction-like mappings, skipping duplicates (FR-3).

    Each mapping should contain at least: account_id, date, amount, raw_description.

    Returns the list of rows actually saved (excluding skipped duplicates) — callers that need to
    act on exactly what was inserted this call (e.g. transfer detection) should use this list
    rather than re-deriving it from the input count, since input count includes skipped duplicates.
    """
    saved: List[Transaction] = []
    for t in transactions:
        result = save_transaction(
            session,
            account_id=t["account_id"],
            date=t["date"],
            amount=t["amount"],
            raw_description=t["raw_description"],
            merchant=t.get("merchant"),
            category=t.get("category"),
            subcategory=t.get("subcategory"),
            type=t.get("type", "Expense"),
            is_refund=t.get("is_refund", False),
            transfer_group_id=t.get("transfer_group_id"),
            source=t.get("source", "bank_import"),
            needs_review=t.get("needs_review", False),
            confidence_score=t.get("confidence_score"),
            raw_transaction_type=t.get("raw_transaction_type"),
            balance=t.get("balance"),
        )
        if result is not None:
            saved.append(result)
    logger.info("Saved %d transactions (duplicates skipped).", len(saved))
    return saved
