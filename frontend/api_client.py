from __future__ import annotations

from datetime import date
from typing import Optional

import httpx

BASE_URL = "http://127.0.0.1:8000"


def get_summary(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    account_id: Optional[int] = None,
) -> dict:
    params = {}
    if date_from is not None:
        params["date_from"] = date_from.isoformat()
    if date_to is not None:
        params["date_to"] = date_to.isoformat()
    if account_id is not None:
        params["account_id"] = account_id
    response = httpx.get(f"{BASE_URL}/summary", params=params, timeout=10.0)
    response.raise_for_status()
    return response.json()


def get_transactions(
    category: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    needs_review: Optional[bool] = None,
    needs_review_reason: Optional[str] = None,
) -> list[dict]:
    params = {}
    if category is not None:
        params["category"] = category
    if date_from is not None:
        params["date_from"] = date_from.isoformat()
    if date_to is not None:
        params["date_to"] = date_to.isoformat()
    if needs_review is not None:
        params["needs_review"] = needs_review
    if needs_review_reason is not None:
        params["needs_review_reason"] = needs_review_reason
    response = httpx.get(f"{BASE_URL}/transactions", params=params, timeout=10.0)
    response.raise_for_status()
    return response.json()


def get_suggested_transfer_match(transaction_id: int) -> Optional[dict]:
    response = httpx.get(f"{BASE_URL}/transactions/{transaction_id}/suggested-transfer-match", timeout=10.0)
    response.raise_for_status()
    return response.json()


def correct_transaction_category(
    transaction_id: int,
    *,
    category: str,
    subcategory: Optional[str] = None,
) -> dict:
    response = httpx.patch(
        f"{BASE_URL}/transactions/{transaction_id}",
        json={"category": category, "subcategory": subcategory},
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


def correct_transaction_is_refund(transaction_id: int, is_refund: bool) -> dict:
    response = httpx.patch(
        f"{BASE_URL}/transactions/{transaction_id}", json={"is_refund": is_refund}, timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


def confirm_transfer_match(transaction_id: int) -> dict:
    """Tier-2 Medium: already auto-linked — clears the soft-confirmation review flag."""
    response = httpx.patch(
        f"{BASE_URL}/transactions/{transaction_id}", json={"confirm_transfer_match": True}, timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


def confirm_transfer_with_id(transaction_id: int, counterpart_id: int) -> dict:
    """Tier-2 Low: not yet linked — links now with the given suggested counterpart."""
    response = httpx.patch(
        f"{BASE_URL}/transactions/{transaction_id}",
        json={"confirm_transfer_with_id": counterpart_id},
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


def reject_transfer_match(transaction_id: int) -> dict:
    response = httpx.patch(
        f"{BASE_URL}/transactions/{transaction_id}", json={"reject_transfer_match": True}, timeout=10.0,
    )
    response.raise_for_status()
    return response.json()
