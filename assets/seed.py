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


def seed_assets(session: Session, config: dict) -> dict:
    """Apply the config, then re-derive asset tags on already-uploaded rows. Caller commits."""
    assets = [_upsert_asset(session, spec) for spec in config.get("assets", [])]
    loans = [_upsert_loan(session, spec) for spec in config.get("loans", [])]
    tagged = reattribute_assets(session)
    return {"assets": len(assets), "loans": len(loans), "tagged": tagged}
