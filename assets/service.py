from __future__ import annotations

"""Asset queries and setup (J6), shared by the API and scripts/seed_assets.py."""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Query, Session

from assets.attribution import reattribute_assets
from backend.models import Asset, AssetAlias, Transaction


class AliasInUseError(ValueError):
    """The alias pattern already identifies another asset."""


def clean_alias(pattern: str) -> str:
    """A blank pattern is a substring of every description, so it would tag every transaction."""
    cleaned = pattern.strip()
    if not cleaned:
        raise ValueError("Asset alias pattern must not be blank.")
    return cleaned


def find_alias(session: Session, pattern: str) -> Optional[AssetAlias]:
    # Case-insensitive, matching how attribution compares patterns to descriptions.
    return session.query(AssetAlias).filter(func.upper(AssetAlias.pattern) == pattern.upper()).one_or_none()


@dataclass
class AssetCashFlow:
    asset: Asset
    income: float
    expense: float

    @property
    def net(self) -> float:
        return self.income - self.expense


def asset_transactions_query(
    session: Session, asset_id: int, date_from: Optional[date] = None, date_to: Optional[date] = None
) -> Query:
    """An asset's transactions, with the same Transfer/superseded exclusions as GET /summary."""
    q = session.query(Transaction).filter(
        Transaction.asset_id == asset_id,
        Transaction.type != "Transfer",
        Transaction.superseded_by_id.is_(None),
    )
    if date_from is not None:
        q = q.filter(Transaction.date >= date_from)
    if date_to is not None:
        q = q.filter(Transaction.date <= date_to)
    return q


def asset_cash_flows(
    session: Session, date_from: Optional[date] = None, date_to: Optional[date] = None
) -> list[AssetCashFlow]:
    """
    Every asset (sold ones included, so their history stays reportable), with income and expense
    split the same way as GET /summary: the Income category is income, everything else nets into
    expense (so a refund credit reduces expense rather than counting as income).
    """
    flows = []
    for asset in session.query(Asset).order_by(Asset.name):
        income = expense = 0.0
        for tx in asset_transactions_query(session, asset.id, date_from, date_to):
            if tx.category == "Income":
                income += tx.amount
            else:
                expense -= tx.amount
        flows.append(AssetCashFlow(asset=asset, income=income, expense=expense))
    return flows


def create_asset(
    session: Session,
    *,
    name: str,
    type: str,
    owner: Optional[str] = None,
    notes: Optional[str] = None,
    is_active: bool = True,
    aliases: tuple[str, ...] = (),
) -> Asset:
    patterns = [clean_alias(p) for p in aliases]
    for pattern in patterns:
        if find_alias(session, pattern) is not None:
            raise AliasInUseError(f"Alias {pattern!r} already identifies another asset.")
    asset = Asset(name=name, type=type, owner=owner, notes=notes, is_active=is_active)
    session.add(asset)
    session.flush()
    for pattern in patterns:
        session.add(AssetAlias(asset_id=asset.id, pattern=pattern))
    session.flush()
    # A new alias can identify rows uploaded before the asset existed.
    reattribute_assets(session)
    return asset
