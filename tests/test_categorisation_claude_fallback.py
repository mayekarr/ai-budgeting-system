from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Base, CategorisationRule
from categorisation.claude_fallback import CONFIDENCE_THRESHOLD, categorise_with_fallback
from categorisation.rules import match_rule


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s


def _fake_tool_use_response(category, subcategory, confidence, merchant_pattern=None):
    tool_block = SimpleNamespace(
        type="tool_use",
        input={"category": category, "subcategory": subcategory, "confidence": confidence,
               "merchant_pattern": merchant_pattern},
    )
    return SimpleNamespace(content=[tool_block])


def test_confident_result_is_promoted_using_the_merchant_pattern_not_the_full_description(session):
    client = MagicMock()
    client.messages.create.return_value = _fake_tool_use_response(
        "Groceries", None, 0.95, merchant_pattern="HILLS MEATS"
    )

    result = categorise_with_fallback(
        session, "HILLS MEATS PTY LTDHILLS Forest Hill 036", client=client
    )

    assert result.category == "Groceries"
    assert result.needs_review is False

    rule = session.query(CategorisationRule).filter_by(source="llm_promoted").one()
    assert rule.pattern == "HILLS MEATS"
    assert rule.match_type == "substring"

    # The promoted rule must actually generalise to a *different* real description from the same
    # merchant, at a different store — the whole point of NFR-4's "never call the API twice" claim.
    match = match_rule(session, "HILLS MEATS PTY LTDHILLS Box Hill South 019")
    assert match is not None
    assert match.category == "Groceries"


def test_hallucinated_merchant_pattern_not_in_the_description_falls_back_to_exact_match(session):
    # A guard against the LLM returning a merchant_pattern that isn't actually present in the
    # description it was given — promoting that as a substring rule could over-match unrelated
    # future transactions. Falls back to the old exact-full-description behaviour instead.
    client = MagicMock()
    client.messages.create.return_value = _fake_tool_use_response(
        "Groceries", None, 0.95, merchant_pattern="SOMETHING UNRELATED"
    )

    categorise_with_fallback(session, "HILLS MEATS PTY LTDHILLS Forest Hill 036", client=client)

    rule = session.query(CategorisationRule).filter_by(source="llm_promoted").one()
    assert rule.pattern == "HILLS MEATS PTY LTDHILLS Forest Hill 036"
    assert rule.match_type == "exact"


def test_missing_merchant_pattern_falls_back_to_exact_match(session):
    client = MagicMock()
    client.messages.create.return_value = _fake_tool_use_response("Groceries", None, 0.95)

    categorise_with_fallback(session, "SOME NEW GROCERY MERCHANT", client=client)

    rule = session.query(CategorisationRule).filter_by(source="llm_promoted").one()
    assert rule.pattern == "SOME NEW GROCERY MERCHANT"
    assert rule.match_type == "exact"


def test_low_confidence_result_flags_needs_review_and_is_not_promoted(session):
    client = MagicMock()
    client.messages.create.return_value = _fake_tool_use_response("Miscellaneous", None, 0.4)

    result = categorise_with_fallback(session, "AMBIGUOUS MERCHANT TEXT", client=client)

    assert result.needs_review is True
    assert result.confidence < CONFIDENCE_THRESHOLD
    assert session.query(CategorisationRule).filter_by(source="llm_promoted").count() == 0


def test_taxonomy_invalid_pairing_is_not_promoted_even_at_high_confidence(session):
    # Schema-legal category, but "Flights" isn't one of Groceries' real subcategories (§4.2) —
    # a permanent rule must never be built from an invalid pairing, regardless of confidence.
    client = MagicMock()
    client.messages.create.return_value = _fake_tool_use_response("Groceries", "Flights", 0.95)

    result = categorise_with_fallback(session, "SOME MERCHANT", client=client)

    assert result.needs_review is True
    assert session.query(CategorisationRule).filter_by(source="llm_promoted").count() == 0


def test_uses_haiku_model_for_cost(session):
    client = MagicMock()
    client.messages.create.return_value = _fake_tool_use_response("Groceries", None, 0.9)

    categorise_with_fallback(session, "WOOLWORTHS 3345", client=client)

    _, kwargs = client.messages.create.call_args
    assert kwargs["model"] == "claude-haiku-4-5-20251001"
