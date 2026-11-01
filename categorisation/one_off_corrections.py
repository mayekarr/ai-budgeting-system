"""
Per-transaction one-off corrections (docs/product-requirements.md FR-9j/FR-9k).

A capital event such as a property sale or settlement can't be recognised from its text, so each is
tagged individually from a gitignored JSON list, keyed on exact date + amount + description. The
list is applied idempotently (a re-run changes 0 rows), so it can be replayed after a `finance.db`
rebuild. Unlike the PATCH correction endpoint, this deliberately creates NO categorisation rule:
a one-off must not generalise to future rows with similar text.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models import Transaction
from backend.needs_review_reasons import LLM_UNAVAILABLE, LOW_CONFIDENCE_CATEGORY, REFUND_AMBIGUITY, TRANSFER_MATCH
from categorisation.taxonomy import is_valid_category

logger = logging.getLogger(__name__)

# Reasons a human-decided tag resolves. Anything else (e.g. unrecognised_account) is unrelated and kept.
_ADDRESSED_REASONS = {LOW_CONFIDENCE_CATEGORY, LLM_UNAVAILABLE, REFUND_AMBIGUITY, TRANSFER_MATCH}
_TYPES = {"Income", "Expense", "Transfer"}


def load_corrections(path: Path) -> list[dict[str, Any]]:
    """The `corrections` list from the JSON file; ValueError with a plain message if the file is bad."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON ({exc}); expected {{\"corrections\": [...]}}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("corrections"), list):
        raise ValueError(f'{path} must be an object with a "corrections" list')
    return data["corrections"]


def _parse(entry: dict[str, Any]) -> tuple[date, float, str, dict[str, Any]] | None:
    """Validated (date, amount, description, target fields), or None for a malformed entry."""
    try:
        day = date.fromisoformat(entry["date"])
        amount = float(entry["amount"])
        description = str(entry["description"]).strip()
        tx_type = entry["type"]
        if tx_type not in _TYPES:
            return None
        expect = entry.get("expect", 1)
        if type(expect) is not int or expect < 1:
            return None
        if tx_type == "Transfer":
            target: dict[str, Any] = {"type": "Transfer", "category": None, "subcategory": None, "is_refund": False}
        else:
            category, subcategory = entry["category"], entry.get("subcategory")
            if not is_valid_category(category, subcategory):
                return None
            # Income rows carry the Income category and nothing else does; a mismatch is a typo.
            if (tx_type == "Income") != (category == "Income"):
                return None
            target = {"type": tx_type, "category": category, "subcategory": subcategory}
            # Only touch the refund flag when the entry says so; auto-detection stays otherwise.
            if "is_refund" in entry:
                target["is_refund"] = bool(entry["is_refund"])
    except (KeyError, TypeError, ValueError):
        return None
    return day, amount, description, target


def _stale_flag(tx: Transaction) -> bool:
    return tx.needs_review and (tx.needs_review_reason is None or tx.needs_review_reason in _ADDRESSED_REASONS)


def apply_corrections(session: Session, entries: list[dict[str, Any]], *, commit: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {
        "changed": 0, "already_applied": 0,
        "not_found": [], "ambiguous": [], "invalid": [], "skipped_grouped": [],
    }
    for entry in entries:
        parsed = _parse(entry) if isinstance(entry, dict) else None
        if parsed is None:
            result["invalid"].append(entry)
            continue
        day, amount, description, target = parsed

        rows = (
            session.query(Transaction)
            .filter(
                Transaction.date == day,
                func.abs(Transaction.amount - amount) < 0.005,
                func.upper(func.trim(Transaction.raw_description)) == description.upper(),
            )
            .all()
        )
        if not rows:
            result["not_found"].append(entry)
            continue
        if len(rows) != entry.get("expect", 1):
            result["ambiguous"].append(entry)
            continue
        # All-or-nothing per entry: never leave a multi-row entry half applied.
        if target["type"] != "Transfer" and any(tx.transfer_group_id is not None for tx in rows):
            result["skipped_grouped"].append(entry)
            continue

        for tx in rows:
            same = all(getattr(tx, field) == value for field, value in target.items())
            if same and not _stale_flag(tx):
                result["already_applied"] += 1
                continue
            for field, value in target.items():
                setattr(tx, field, value)
            tx.confidence_score = 1.0
            if _stale_flag(tx):
                tx.needs_review = False
                tx.needs_review_reason = None
            result["changed"] += 1
    if commit:
        session.commit()
    else:
        session.flush()
    logger.info("One-off corrections: %d changed, %d already applied.", result["changed"], result["already_applied"])
    return result
