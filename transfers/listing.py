"""
What the Transfers page shows: every live `Transfer` row, split into

  - pairs: rows linked into a TransferGroup (the two or more legs of one move between the user's own
    accounts), with the group's detection tier and confidence so a tentative (Tier-2 Medium) match
    can be told from a confident one;
  - lone transfers: Transfer rows with no group, i.e. the other side isn't imported (a card payment
    whose account statement ends earlier, for example).

Superseded rows are never shown. A date or account filter keeps a pair when ANY leg matches, and the
pair still lists all of its legs, so the other side of a move is never hidden by the filter.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import Account, Transaction, TransferGroup


def _leg(tx: Transaction, account_name: str) -> dict[str, Any]:
    return {
        "id": tx.id,
        "account_id": tx.account_id,
        "account_name": account_name,
        "date": tx.date,
        "amount": tx.amount,
        "raw_description": tx.raw_description,
    }


def list_transfers(
    session: Session,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    account_id: Optional[int] = None,
) -> dict[str, list[dict[str, Any]]]:
    rows = (
        session.query(Transaction, Account.name)
        .join(Account, Transaction.account_id == Account.id)
        .filter(Transaction.type == "Transfer", Transaction.superseded_by_id.is_(None))
        .all()
    )

    def in_range(leg: dict[str, Any]) -> bool:
        return (date_from is None or leg["date"] >= date_from) and (date_to is None or leg["date"] <= date_to)

    def on_account(leg: dict[str, Any]) -> bool:
        return account_id is None or leg["account_id"] == account_id

    legs_by_group: dict[int, list[dict[str, Any]]] = {}
    lone: list[dict[str, Any]] = []
    for tx, account_name in rows:
        leg = _leg(tx, account_name)
        if tx.transfer_group_id is None:
            if in_range(leg) and on_account(leg):
                lone.append(leg)
        else:
            legs_by_group.setdefault(tx.transfer_group_id, []).append(leg)

    groups = {
        g.id: g for g in session.query(TransferGroup).filter(TransferGroup.id.in_(list(legs_by_group)))
    }
    pairs = []
    for group_id, legs in legs_by_group.items():
        if group_id not in groups:
            continue
        if not any(in_range(leg) for leg in legs) or not any(on_account(leg) for leg in legs):
            continue
        legs.sort(key=lambda leg: leg["amount"])  # money out first, money in last
        pairs.append(
            {
                "group_id": group_id,
                "detection_tier": groups[group_id].detection_tier,
                "confidence": groups[group_id].confidence,
                "date": min(leg["date"] for leg in legs),
                "amount": max(abs(leg["amount"]) for leg in legs),
                "legs": legs,
            }
        )

    pairs.sort(key=lambda p: (p["date"], p["group_id"]), reverse=True)
    lone.sort(key=lambda leg: (leg["date"], leg["id"]), reverse=True)
    return {"pairs": pairs, "lone": lone}
