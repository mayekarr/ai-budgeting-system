"""
Rebuild the transfer groups an existing database holds, using the current rules.

Before 2026-11-01 Tier 2 matched amounts "within $2 or 1%", ignored the bank's transaction type and let a
row join someone else's group, so card purchases, ATM withdrawals and credits from other people were
paired with real transfers and disappeared from income and spending. This takes apart every weaker group
(any Tier-2 group, and any group with more than two legs), puts its rows back to ordinary income/expense,
and detects them again from scratch: all of Tier 1 first (account number / reference), then Tier 2
(exact amount, a transfer-capable bank type). Tier-1 groups with two legs are final and left alone.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from backend.models import Transaction, TransferGroup
from backend.needs_review_reasons import TRANSFER_MATCH
from categorisation.rules import first_matching_rule, load_active_rules
from transfers.card_payments import reclassify_card_payments
from transfers.detection import is_never_transfer, process_transfer_detection
from transfers.own_accounts import reclassify_own_account_transfers

Restore = dict[int, tuple[Optional[str], Optional[str]]]


def rebuild_transfer_groups(session: Session, restore_categories: Optional[Restore] = None) -> dict[str, int]:
    """
    `restore_categories` maps a transaction id to its (category, subcategory) before the groups were
    first tidied (a confident link used to wipe it); a freed row without one is run through the rules
    and otherwise left as the unplaced `Miscellaneous` default. Returns counts. The caller commits.
    """
    groups = [g for g in session.query(TransferGroup) if g.detection_tier >= 2 or len(g.members) > 2]
    freed: list[Transaction] = []
    for group in groups:
        for member in list(group.members):
            member.transfer_group = None
            member.type = "Income" if member.amount > 0 else "Expense"
            if member.needs_review_reason == TRANSFER_MATCH:
                member.needs_review = False
                member.needs_review_reason = None
            freed.append(member)
        session.flush()
        session.delete(group)
    session.flush()

    rules = load_active_rules(session)
    for tx in freed:
        if tx.category is not None:
            continue
        if restore_categories and tx.id in restore_categories and restore_categories[tx.id][0] is not None:
            tx.category, tx.subcategory = restore_categories[tx.id]
            continue
        match = first_matching_rule(rules, tx.raw_description)
        if match is not None:
            tx.category, tx.subcategory = match.category, match.subcategory
        else:
            tx.category, tx.subcategory, tx.confidence_score = "Miscellaneous", None, 0.0

    # Text-decided transfers first, so a debit to Macquarie is never paired with something by coincidence.
    own_account = reclassify_own_account_transfers(session)
    # Same guard as the upload path: an ATO refund, rent credit or capital event is never made a Transfer.
    ordered = sorted((t for t in freed if not is_never_transfer(t)), key=lambda t: (t.date, t.id))
    for tx in ordered:
        process_transfer_detection(session, tx, tiers=(1,))
    for tx in ordered:
        process_transfer_detection(session, tx, tiers=(2,))
    card_payments = reclassify_card_payments(session)
    session.flush()

    relinked = sum(1 for tx in freed if tx.transfer_group_id is not None)
    return {
        "dissolved_groups": len(groups),
        "freed_rows": len(freed),
        "relinked_rows": relinked,
        "now_ordinary_rows": sum(1 for tx in freed if tx.type != "Transfer"),
        "own_account_transfers": own_account,
        "card_payments_unpaired": card_payments,
    }


def relink_by_reference(session: Session) -> int:
    """
    Pair rows that have lost their pair but still share an account number or reference with an exact
    opposite amount on another account (Tier 1 only; never on amount alone). Needed when one click
    unlinked a whole group, or after any other unlink: the rows were no longer in a group, so no rebuild
    would look at them. Safe to re-run; returns how many rows were linked.
    """
    rows = (
        session.query(Transaction)
        .filter(
            Transaction.superseded_by_id.is_(None),
            Transaction.transfer_group_id.is_(None),
            Transaction.type != "Transfer",
        )
        .order_by(Transaction.date, Transaction.id)
        .all()
    )
    rows = [tx for tx in rows if not is_never_transfer(tx)]
    for tx in rows:
        process_transfer_detection(session, tx, tiers=(1,))
    session.flush()
    return sum(1 for tx in rows if tx.transfer_group_id is not None)
