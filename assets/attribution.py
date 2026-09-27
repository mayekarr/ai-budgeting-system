from __future__ import annotations

"""
Asset attribution (J6): which Asset, if any, a transaction belongs to. Tags only — never changes a
transaction's category or type.

First match wins:
  1. The description names a *loan* account (by an AccountAlias, e.g. "34-188-5257") that is
     linked to an asset. Structural, so it survives the bank rewording the line.
  2. The description matches an AssetAlias pattern (e.g. "6 JERICHO CT" on a rent credit).
  3. The transaction's own account is linked to an asset (e.g. a loan statement's own rows).

A blank pattern would match everything, so assets/service.py's clean_alias() rejects one before it
is ever stored.

A shared everyday account (the real JC account also carries card autopay and donations) is never
linked wholesale, so its unrelated rows stay untagged.
"""

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from backend.models import Account, AccountAlias, AssetAlias, Transaction
from transfers.aliases import alias_matches_text

LOAN_ACCOUNT_TYPE = "Loan"


@dataclass(frozen=True)
class AssetLookups:
    """Everything attribution needs, loaded once per upload rather than queried per row."""

    loan_aliases: list[tuple[str, int]]  # (raw_identifier, asset_id)
    asset_aliases: list[tuple[str, int]]  # (pattern, asset_id)
    account_assets: dict[int, int]  # account_id -> asset_id


def load_asset_lookups(session: Session) -> AssetLookups:
    loan_aliases = [
        (alias.raw_identifier, account.asset_id)
        for alias, account in session.query(AccountAlias, Account)
        .join(Account, AccountAlias.account_id == Account.id)
        .filter(Account.account_type == LOAN_ACCOUNT_TYPE, Account.asset_id.is_not(None))
    ]
    asset_aliases = [(a.pattern, a.asset_id) for a in session.query(AssetAlias)]
    account_assets = {
        account_id: asset_id
        for account_id, asset_id in session.query(Account.id, Account.asset_id).filter(
            Account.asset_id.is_not(None)
        )
    }
    return AssetLookups(loan_aliases, asset_aliases, account_assets)


def attribute_asset(raw_description: str, account_id: int, lookups: AssetLookups) -> Optional[int]:
    for raw_identifier, asset_id in lookups.loan_aliases:
        if alias_matches_text(raw_identifier, raw_description):
            return asset_id
    upper = raw_description.upper()
    for pattern, asset_id in lookups.asset_aliases:
        if pattern.upper() in upper:
            return asset_id
    return lookups.account_assets.get(account_id)


def reattribute_assets(session: Session) -> int:
    """
    Re-derive every transaction's asset from the current setup, e.g. after an asset, alias or loan
    link is added, moved or removed. All rows, not just untagged ones: every tag is derived (nothing
    sets one by hand), so this is what stops a relinked or unlinked loan leaving stale tags behind.
    Returns how many rows changed.
    """
    lookups = load_asset_lookups(session)
    changed = 0
    for tx in session.query(Transaction):
        asset_id = attribute_asset(tx.raw_description, tx.account_id, lookups)
        if tx.asset_id != asset_id:
            tx.asset_id = asset_id
            changed += 1
    return changed
