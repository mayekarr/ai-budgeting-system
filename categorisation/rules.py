from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from backend.models import CategorisationRule

_MATCH_TYPE_ORDER = {"exact": 0, "substring": 1, "regex": 2}


@dataclass
class RuleMatch:
    category: str
    subcategory: Optional[str]
    confidence: float
    rule_id: int


def pattern_matches(pattern: str, match_type: str, text: str) -> bool:
    """
    The project's one canonical pattern-matching semantics (exact/substring/regex), shared by rule
    matching here and by transfers/refunds.py's counterparty resolution — a second hand-rolled copy
    would risk silently diverging from this as match_type handling evolves.
    """
    if match_type == "exact":
        return text.strip().upper() == pattern.strip().upper()
    if match_type == "substring":
        return pattern.upper() in text.upper()
    if match_type == "regex":
        return re.search(pattern, text, re.IGNORECASE) is not None
    return False


def _matches(rule: CategorisationRule, text: str) -> bool:
    return pattern_matches(rule.pattern, rule.match_type, text)


def match_rule(session: Session, raw_description: str) -> Optional[RuleMatch]:
    """
    Match a transaction's raw description against active CategorisationRule rows.

    Match order: exact, then substring, then regex; within a match type, lower `priority` wins.
    A rule match is always full confidence (1.0) — confidence scoring only applies to the LLM
    fallback path (categorisation/claude_fallback.py).
    """
    # Sorted once in Python by (match_type, priority) — that key already fully determines order,
    # so an additional SQL-side ORDER BY on priority alone would be redundant work the Python sort
    # immediately overrides.
    rules = session.query(CategorisationRule).filter(CategorisationRule.is_active.is_(True)).all()
    rules.sort(key=lambda r: (_MATCH_TYPE_ORDER.get(r.match_type, 99), r.priority))

    for rule in rules:
        if _matches(rule, raw_description):
            return RuleMatch(
                category=rule.category,
                subcategory=rule.subcategory,
                confidence=1.0,
                rule_id=rule.id,
            )
    return None
