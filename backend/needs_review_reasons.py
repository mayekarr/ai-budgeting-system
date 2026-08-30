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

# J8 (historical backfill) will use this for the 4 explicitly-flagged remap items
# (docs/product-requirements.md §4.2.1) — not produced by any code yet.
BACKFILL_FLAGGED = "backfill_flagged"

ALL_REASONS = (
    LOW_CONFIDENCE_CATEGORY,
    UNRECOGNISED_ACCOUNT,
    REFUND_AMBIGUITY,
    TRANSFER_MATCH,
    BACKFILL_FLAGGED,
)
