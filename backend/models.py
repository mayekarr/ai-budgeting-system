from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


class Account(Base):
    """One of the user's real-world bank accounts."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    institution: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    owner: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    account_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    aliases: Mapped[list["AccountAlias"]] = relationship(back_populates="account")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")


class AccountAlias(Base):
    """
    A raw account identifier as it appears on a bank statement, mapped to one Account.

    One Account can have multiple raw identifiers (e.g. "Card ending 7128" and the masked
    full number "453030xxxxxx7128" for the same NAB credit card).
    """

    __tablename__ = "account_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    raw_identifier: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)

    account: Mapped["Account"] = relationship(back_populates="aliases")


class TransferGroup(Base):
    """
    A set of 2+ Transaction rows that are legs of the same inter-account transfer.

    A group of size 2 covers the common pairwise case; 3+ covers a same-day chain across more
    than two of the user's own accounts (e.g. RC -> MAC -> MACACC).
    """

    __tablename__ = "transfer_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    detection_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    members: Mapped[list["Transaction"]] = relationship(back_populates="transfer_group")


class CategorisationRule(Base):
    """A rule matched against a transaction's raw description/merchant before falling back to the LLM."""

    __tablename__ = "categorisation_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    pattern: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    match_type: Mapped[str] = mapped_column(String(20), nullable=False, default="substring")
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    subcategory: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="seeded")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Transaction(Base):
    """
    A single bank transaction.

    Amounts are stored as floats; negative values represent debits (spending), positive values
    represent credits (income/refunds/transfers-in).
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    raw_description: Mapped[str] = mapped_column(String(255), nullable=False)
    merchant: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    subcategory: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    type: Mapped[str] = mapped_column(String(20), nullable=False, default="Expense", index=True)
    is_refund: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    transfer_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("transfer_groups.id"), nullable=True, index=True
    )
    # Set on a PENDING (e.g. PURCHASE AUTHORISATION) row once its SETTLED counterpart is
    # identified — the pending row stays as an individually queryable record (NFR-6), but rollups
    # exclude it (superseded_by_id IS NOT NULL) so the one real-world charge isn't double-counted.
    superseded_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("transactions.id"), nullable=True, index=True
    )

    source: Mapped[str] = mapped_column(String(20), nullable=False, default="bank_import")
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    raw_transaction_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    balance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    account: Mapped["Account"] = relationship(back_populates="transactions")
    transfer_group: Mapped[Optional["TransferGroup"]] = relationship(back_populates="members")
