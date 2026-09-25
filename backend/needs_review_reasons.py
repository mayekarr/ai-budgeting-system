from __future__ import annotations

"""
`Transaction.needs_review_reason` values (J5, docs/design-logic-and-ux.md §3.2). A plain constants
module with no other imports, so ingestion/categorisation/transfers/backend can all depend on it
without creating an import cycle with backend.models/backend.api.
"""

LOW_CONFIDENCE_CATEGORY = "low_confidence_category"
UNRECOGNISED_ACCOUNT = "unrecognised_account"
REFUND_AMBIGUITY = "refund_ambiguity"
TRANSFER_MATCH = "transfer_match"

# The Claude API call itself failed (no api_key/auth_token/credentials configured, auth rejected,
# network/rate limit/outage) rather than returning a genuinely low-confidence result -- distinct
# from LOW_CONFIDENCE_CATEGORY because it means every future upload will hit the same wall until
# fixed, not just this one merchant (2026-09-25, categorisation/claude_fallback.py). Addressed by
# the same action as LOW_CONFIDENCE_CATEGORY -- a manual category correction.
LLM_UNAVAILABLE = "llm_unavailable"

# J8 (historical backfill) will use this for the 4 explicitly-flagged remap items
# (docs/product-requirements.md §4.2.1) — not produced by any code yet.
BACKFILL_FLAGGED = "backfill_flagged"

ALL_REASONS = (
    LOW_CONFIDENCE_CATEGORY,
    LLM_UNAVAILABLE,
    UNRECOGNISED_ACCOUNT,
    REFUND_AMBIGUITY,
    TRANSFER_MATCH,
    BACKFILL_FLAGGED,
)

# Precedence, lowest to highest, for two situations that must agree with each other
# (/code-review finding — they previously used two separate, hand-written mechanisms):
#   1. Upload persists a row with more than one reason live at once (backend/api.py) — the
#      highest-priority one is stored.
#   2. A later Tier-2 transfer match (transfers/detection.py) decides whether it may supersede an
#      already-stored reason.
# unrecognised_account ranks highest and is never superseded: it's about the account's identity,
# not this transaction's classification, and (per ingestion/account_resolution.py) is only ever
# raised once per account, so losing it would mean losing it for good. transfer_match ranks above
# low_confidence_category/llm_unavailable/refund_ambiguity, which are moot once a transaction is
# genuinely reclassified as a Transfer (GET /summary excludes Transfer rows outright either way).
# low_confidence_category and llm_unavailable are the same precedence tier -- a single
# categorisation attempt only ever produces one or the other, never both, so their relative order
# doesn't matter.
_PRECEDENCE_ORDER = (
    LOW_CONFIDENCE_CATEGORY,
    LLM_UNAVAILABLE,
    REFUND_AMBIGUITY,
    TRANSFER_MATCH,
    UNRECOGNISED_ACCOUNT,
)
_PRECEDENCE_RANK = {reason: rank for rank, reason in enumerate(_PRECEDENCE_ORDER)}


def highest_priority_reason(*reasons) -> str | None:
    """The highest-priority reason among the given candidates (None values ignored)."""
    present = [r for r in reasons if r is not None]
    if not present:
        return None
    return max(present, key=lambda r: _PRECEDENCE_RANK[r])


def should_supersede(existing: str, candidate: str) -> bool:
    """Whether `candidate` is allowed to replace an already-stored `existing` reason."""
    return _PRECEDENCE_RANK[candidate] >= _PRECEDENCE_RANK[existing]
