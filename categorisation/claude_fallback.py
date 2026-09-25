from __future__ import annotations

"""
LLM fallback categorisation, used only when no CategorisationRule matches (categorisation/rules.py).

Model: Claude Haiku 4.5 — a lightweight classification task doesn't need a larger model; keeps
running cost down (NFR-4). Below CONFIDENCE_THRESHOLD, the result is flagged for manual review
(FR-10) instead of silently trusted. A confident result is promoted to a new CategorisationRule
(source=llm_promoted), preferring a substring rule on the extracted stable merchant_pattern (not
the full, often per-transaction-unique raw description) so a *different* future transaction from
the same merchant also matches it — a rule scoped to one exact description would rarely reoccur
verbatim in real bank text and would defeat the "never call the API twice for this merchant"
intent this exists for. This is also how a user correction (FR-9) and an LLM result end up using
the same learning mechanism.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import anthropic
from sqlalchemy.orm import Session

from backend.models import CategorisationRule
from backend.needs_review_reasons import LLM_UNAVAILABLE
from categorisation.taxonomy import TAXONOMY, is_valid_category

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
CONFIDENCE_THRESHOLD = 0.7

# The exact, stable substring of the SDK's own error message for "no api_key/auth_token/
# credentials configured at all" (anthropic._client.Anthropic._validate_headers) -- used to tell
# that specific, expected case apart from an unrelated TypeError elsewhere in this call, which
# must not be silently swallowed (/code-review finding).
_MISSING_AUTH_MESSAGE_MARKER = "Could not resolve authentication method"

_TOOL_NAME = "categorise_transaction"
_TOOL_SCHEMA = {
    "name": _TOOL_NAME,
    "description": "Assign a category and subcategory to a bank transaction description.",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": list(TAXONOMY.keys())},
            "subcategory": {"type": ["string", "null"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "merchant_pattern": {
                "type": ["string", "null"],
                "description": (
                    "The stable merchant-identifying substring of the description — excluding "
                    "store numbers, locations, or other per-transaction suffixes — that would "
                    "still appear in a future transaction from the same merchant. Must be an "
                    "exact substring of the transaction description given. Null if none applies."
                ),
            },
        },
        "required": ["category", "confidence"],
    },
}


@dataclass
class FallbackResult:
    category: str
    subcategory: Optional[str]
    confidence: float
    needs_review: bool
    # None for a genuine (if low-confidence) model judgement; LLM_UNAVAILABLE when the API call
    # itself failed and no real judgement was ever made -- callers need to tell these apart (a
    # future upload keeps hitting the same wall in the latter case, unlike the former).
    reason: Optional[str] = None


def _get_client(client: Optional["anthropic.Anthropic"]) -> "anthropic.Anthropic":
    if client is not None:
        return client
    return anthropic.Anthropic()


def _build_prompt(raw_description: str) -> str:
    categories = ", ".join(TAXONOMY.keys())
    return (
        "Categorise this bank transaction description into exactly one of these categories: "
        f"{categories}. Include a subcategory if one of the category's known subcategories "
        f"clearly applies, otherwise null. Give a confidence between 0 and 1. Also extract the "
        f"stable merchant_pattern substring, if the description clearly names a merchant.\n\n"
        f"Transaction description: {raw_description}"
    )


def _unavailable_result() -> FallbackResult:
    """Shared outcome for both "API unavailable" except branches below (/code-review finding —
    kept them from silently diverging if this outcome ever needs to change)."""
    return FallbackResult(category="Miscellaneous", subcategory=None, confidence=0.0,
                           needs_review=True, reason=LLM_UNAVAILABLE)


def categorise_with_fallback(
    session: Session,
    raw_description: str,
    *,
    client: Optional["anthropic.Anthropic"] = None,
) -> FallbackResult:
    """Call Claude for a transaction no rule matched, and promote a confident result to a new rule."""
    active_client = _get_client(client)

    try:
        response = active_client.messages.create(
            model=MODEL,
            max_tokens=200,
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=[{"role": "user", "content": _build_prompt(raw_description)}],
        )
    except TypeError as exc:
        # Only the SDK's specific "no auth resolvable" TypeError means "API unavailable" -- an
        # unrelated TypeError (e.g. a future bad argument to messages.create) is a real bug and
        # must propagate, not be silently downgraded to a review flag (/code-review finding).
        if _MISSING_AUTH_MESSAGE_MARKER not in str(exc):
            raise
        logger.warning("Claude fallback unavailable for %r (no credentials configured); flagged for manual review.",
                        raw_description)
        return _unavailable_result()
    except anthropic.AnthropicError as exc:
        # Real API failures (auth rejected, network, rate limit, outage) -- distinct from a bad
        # local call, and just as unable to produce a real categorisation as the TypeError case.
        logger.warning("Claude fallback unavailable for %r (%s); flagged for manual review.",
                        raw_description, exc)
        return _unavailable_result()

    tool_use = next(block for block in response.content if block.type == "tool_use")
    category = tool_use.input["category"]
    subcategory = tool_use.input.get("subcategory")
    confidence = float(tool_use.input["confidence"])

    # The tool schema constrains `category` via enum but not `subcategory` — Claude can still
    # return a schema-legal but taxonomy-invalid pairing (e.g. Groceries/Flights). A promoted rule
    # is permanent and auto-applies to every future match, so an invalid pairing must never be
    # promoted, regardless of confidence — it's flagged for review instead.
    valid_pair = is_valid_category(category, subcategory)
    needs_review = confidence < CONFIDENCE_THRESHOLD or not valid_pair

    if not needs_review:
        # Prefer the extracted merchant_pattern (a substring rule generalises to future
        # transactions from the same merchant — the whole point of the NFR-4 cost saving this
        # promotion exists for). Guard against a hallucinated pattern that isn't actually present
        # in the description it was extracted from — promoting that as a substring rule risks
        # over-matching unrelated future transactions — by falling back to the old exact-match-on-
        # the-full-description behaviour, which is narrower (safe) even though it won't generalise.
        merchant_pattern = tool_use.input.get("merchant_pattern")
        if merchant_pattern and merchant_pattern.upper() in raw_description.upper():
            pattern, match_type = merchant_pattern, "substring"
        else:
            pattern, match_type = raw_description, "exact"

        session.add(
            CategorisationRule(
                pattern=pattern,
                match_type=match_type,
                category=category,
                subcategory=subcategory,
                priority=500,
                source="llm_promoted",
                is_active=True,
            )
        )
        logger.info("Promoted LLM categorisation to a new %s rule (%r) for %r -> %s",
                     match_type, pattern, raw_description, category)
    elif not valid_pair:
        logger.warning("LLM returned taxonomy-invalid category/subcategory (%r/%r) for %r; flagged for review, not promoted",
                        category, subcategory, raw_description)
    else:
        logger.info("LLM categorisation below confidence threshold (%.2f) for %r; flagged for review",
                     confidence, raw_description)

    return FallbackResult(category=category, subcategory=subcategory, confidence=confidence, needs_review=needs_review)
