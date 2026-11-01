"""
One-off tidy-up for Transfer rows that still carry a category from before they became a Transfer.

The category is meaningless on a Transfer (GET /summary excludes the type outright) but misleading in
a raw query or a drill-in. A tentative pair (Tier-2 Medium, confidence below 1.0) is left alone,
because rejecting the match restores the row to Income/Expense and needs its category back. New
confident links already clear the category as they are made (`link_transfer_pair`).
"""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.models import Transaction, TransferGroup


def clear_transfer_categories(session: Session) -> int:
    """Null category/subcategory on confident or groupless Transfers. Idempotent; caller commits."""
    rows = (
        session.query(Transaction)
        .outerjoin(TransferGroup, Transaction.transfer_group_id == TransferGroup.id)
        .filter(
            Transaction.type == "Transfer",
            or_(Transaction.category.isnot(None), Transaction.subcategory.isnot(None)),
            or_(Transaction.transfer_group_id.is_(None), TransferGroup.confidence >= 1.0),
        )
        .all()
    )
    for tx in rows:
        tx.category = None
        tx.subcategory = None
    session.flush()
    return len(rows)
