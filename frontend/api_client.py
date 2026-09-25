from __future__ import annotations

import functools
from datetime import date
from typing import Optional

import httpx
import streamlit as st

BASE_URL = "http://127.0.0.1:8000"
_TIMEOUT_SECONDS = 10.0

# Reads are cached because Streamlit reruns the whole page on every widget click. Every write
# below clears the cache, so the dashboard's own changes show up immediately; the TTL only bounds
# how stale things get after a change made outside the dashboard (e.g. a statement uploaded
# straight to the API — the dashboard has no upload control).
_READ_CACHE_TTL_SECONDS = 30


@functools.cache
def _client() -> httpx.Client:
    # One client per process: building an httpx.Client costs ~200ms on this machine, and
    # httpx.get()/httpx.patch() build a new one on every call (measured 2026-09-25: ~233ms per
    # request vs ~9ms reused). httpx.Client is thread-safe, which matters because Streamlit
    # serves each browser session from its own thread.
    return httpx.Client(base_url=BASE_URL, timeout=_TIMEOUT_SECONDS)


def _get(path: str, params: Optional[dict] = None):
    response = _client().get(path, params=params)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=_READ_CACHE_TTL_SECONDS, show_spinner=False)
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
    return _get("/summary", params)


@st.cache_data(ttl=_READ_CACHE_TTL_SECONDS, show_spinner=False)
def get_transactions(
    category: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    needs_review: Optional[bool] = None,
    needs_review_reason: Optional[str] = None,
    transfer_group_id: Optional[int] = None,
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
    if transfer_group_id is not None:
        params["transfer_group_id"] = transfer_group_id
    return _get("/transactions", params)


@st.cache_data(ttl=_READ_CACHE_TTL_SECONDS, show_spinner=False)
def get_suggested_transfer_match(transaction_id: int) -> Optional[dict]:
    return _get(f"/transactions/{transaction_id}/suggested-transfer-match")


def _patch_transaction(transaction_id: int, payload: dict) -> dict:
    try:
        response = _client().patch(f"/transactions/{transaction_id}", json=payload)
        response.raise_for_status()
        return response.json()
    finally:
        # Cleared even when the write fails, since the backend may have applied part of it. Not
        # airtight across browser tabs: a read already in flight in another tab can re-cache
        # pre-write data for up to the TTL (low-priority backlog item in docs/next-steps.md).
        get_summary.clear()
        get_transactions.clear()
        get_suggested_transfer_match.clear()


def correct_transaction_category(
    transaction_id: int,
    *,
    category: str,
    subcategory: Optional[str] = None,
) -> dict:
    return _patch_transaction(transaction_id, {"category": category, "subcategory": subcategory})


def correct_transaction_is_refund(transaction_id: int, is_refund: bool) -> dict:
    return _patch_transaction(transaction_id, {"is_refund": is_refund})


def confirm_transfer_match(transaction_id: int) -> dict:
    """Tier-2 Medium: already auto-linked — clears the soft-confirmation review flag."""
    return _patch_transaction(transaction_id, {"confirm_transfer_match": True})


def confirm_transfer_with_id(transaction_id: int, counterpart_id: int) -> dict:
    """Tier-2 Low: not yet linked — links now with the given suggested counterpart."""
    return _patch_transaction(transaction_id, {"confirm_transfer_with_id": counterpart_id})


def reject_transfer_match(transaction_id: int) -> dict:
    return _patch_transaction(transaction_id, {"reject_transfer_match": True})
