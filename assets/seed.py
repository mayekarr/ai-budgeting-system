from __future__ import annotations

"""
Sets up the user's real assets and loan accounts from a local JSON file (J6). The real file,
config/assets.local.json, is gitignored because it holds loan account numbers;
config/assets.example.json shows the shape.

Idempotent: assets are keyed by name and loans by loan number, so re-running after editing the file
updates in place rather than duplicating.
"""

import json
from pathlib import Path

from sqlalchemy.orm import Session

from assets.attribution import LOAN_ACCOUNT_TYPE, reattribute_assets
from assets.service import clean_alias, find_alias
from backend.models import Account, AccountAlias, Asset, AssetAlias

_ASSET_FIELDS = ("type", "owner", "notes", "is_active")


def load_config(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _upsert_asset(session: Session, spec: dict) -> Asset:
    asset = session.query(Asset).filter_by(name=spec["name"]).one_or_none()
    if asset is None:
        asset = Asset(name=spec["name"], type=spec["type"])
        session.add(asset)
    for field in _ASSET_FIELDS:
        if field in spec:
            setattr(asset, field, spec[field])
    session.flush()

    for raw_pattern in spec.get("aliases", []):
        pattern = clean_alias(raw_pattern)
        alias = find_alias(session, pattern)
        if alias is None:
            session.add(AssetAlias(asset_id=asset.id, pattern=pattern))
        else:
            # Moved to this asset in the config (or already here): update in place.
            alias.asset_id = asset.id
        session.flush()
    return asset


def _upsert_loan(session: Session, spec: dict) -> Account:
    asset = session.query(Asset).filter_by(name=spec["asset"]).one_or_none()
    if asset is None:
        raise ValueError(f"Loan {spec['number']} names unknown asset {spec['asset']!r}")

    alias = session.query(AccountAlias).filter_by(raw_identifier=spec["number"]).one_or_none()
    if alias is None:
        account = Account(name=spec["name"])
        session.add(account)
        session.flush()
        session.add(AccountAlias(account_id=account.id, raw_identifier=spec["number"]))
    else:
        account = alias.account
    account.name = spec["name"]
    account.account_type = LOAN_ACCOUNT_TYPE
    account.asset_id = asset.id
    session.flush()
    return account


def _upsert_account(session: Session, spec: dict) -> Account:
    """
    A plain account (e.g. a Macquarie account, whose statement names the account rather than giving a
    number) keyed by its aliases. An alias already registered, including by an upload that auto-created
    the account from the raw identifier, selects that account, which is then renamed and completed.
    """
    identifiers = list(dict.fromkeys(i.strip() for i in spec.get("aliases", []) if i.strip()))  # no repeats
    if not identifiers:
        raise ValueError(f"Account {spec['name']!r} needs at least one alias.")
    existing = session.query(AccountAlias).filter(AccountAlias.raw_identifier.in_(identifiers)).all()
    owners = {alias.account_id for alias in existing}
    if len(owners) > 1:
        raise ValueError(f"Aliases for account {spec['name']!r} already belong to different accounts.")

    if any(alias.account.account_type == LOAN_ACCOUNT_TYPE for alias in existing):
        raise ValueError(f"An alias for account {spec['name']!r} belongs to a loan account; list loans under 'loans'.")

    account = existing[0].account if existing else Account(name=spec["name"])
    if not existing:
        session.add(account)
        session.flush()
    account.name = spec["name"]
    for field in ("institution", "owner", "account_type"):
        if field in spec:
            setattr(account, field, spec[field])
    known = {alias.raw_identifier for alias in existing}
    for identifier in identifiers:
        if identifier not in known:
            session.add(AccountAlias(account_id=account.id, raw_identifier=identifier))
    session.flush()
    return account


def _prune_aliases(session: Session, specs: list[dict], assets: list[Asset]) -> int:
    """
    For an asset whose entry lists `aliases`, the file is the source of truth: a stored alias it no longer
    names is removed, so narrowing a pattern in the file actually takes effect. An asset whose entry has no
    `aliases` key is left alone (its aliases may have been added through POST /assets). Run after every asset
    is upserted, so an alias the file moved to another asset belongs to that asset by now and is not touched.
    """
    removed = 0
    for spec, asset in zip(specs, assets):
        if "aliases" not in spec:
            continue
        kept = {clean_alias(p) for p in spec["aliases"]}
        for alias in session.query(AssetAlias).filter_by(asset_id=asset.id).all():
            if alias.pattern not in kept:
                session.delete(alias)
                removed += 1
    session.flush()
    return removed


def seed_assets(session: Session, config: dict) -> dict:
    """Apply the config, then re-derive asset tags on already-uploaded rows. Caller commits."""
    specs = config.get("assets", [])
    assets = [_upsert_asset(session, spec) for spec in specs]
    aliases_removed = _prune_aliases(session, specs, assets)
    loans = [_upsert_loan(session, spec) for spec in config.get("loans", [])]
    accounts = [_upsert_account(session, spec) for spec in config.get("accounts", [])]
    tagged = reattribute_assets(session)
    return {
        "assets": len(assets), "loans": len(loans), "accounts": len(accounts), "tagged": tagged,
        "aliases_removed": aliases_removed,
    }
