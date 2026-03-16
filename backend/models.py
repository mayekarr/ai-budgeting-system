from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


class Transaction(Base):
    """
    Represents a single bank transaction.

    Amounts are stored as floats; negative values represent debits (spending),
    positive values represent credits (income/refunds).
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Core transaction details
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    merchant: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)

    # Categorisation
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    subcategory: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    # Financial context
    currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, index=True)
    account_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    # ML / heuristic metadata
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Audit metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

