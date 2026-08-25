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
) -> list[dict]:
    params = {}
    if category is not None:
        params["category"] = category
    if date_from is not None:
        params["date_from"] = date_from.isoformat()
    if date_to is not None:
        params["date_to"] = date_to.isoformat()
    response = httpx.get(f"{BASE_URL}/transactions", params=params, timeout=10.0)
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
