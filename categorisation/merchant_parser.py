from __future__ import annotations

import re


def _normalize_description(description: str) -> str:
    """
    Normalize a raw transaction description for easier matching.

    - Uppercases
    - Removes extra whitespace
    """
    normalized = description.upper().strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def extract_merchant(description: str) -> str:
    """
    Extract a human-friendly merchant name from a raw bank description.

    This is intentionally simple and rule-based for MVP purposes.

    Examples:
        "UBER TRIP"        -> "Uber"
        "WOOLWORTHS 3345"  -> "Woolworths"
        "NETFLIX.COM"      -> "Netflix"

    If no known merchant is found, returns "Unknown".
    """
    if not description:
        return "Unknown"

    desc = _normalize_description(description)

    # Known merchant patterns (simple substring search).
    if "UBER" in desc:
        return "Uber"
    if "WOOLWORTHS" in desc:
        return "Woolworths"
    if "NETFLIX" in desc:
        return "Netflix"
    if "AMAZON" in desc:
        return "Amazon"

    # Fallback: attempt to strip numbers and domains and title-case the first word.
    # This is deliberately conservative for predictability.
    no_digits = re.sub(r"\d+", "", desc)
    no_domain = re.sub(r"\.COM\b", "", no_digits)
    no_domain = re.sub(r"\.CO\.UK\b", "", no_domain)
    parts = no_domain.strip().split(" ")

    if parts and parts[0]:
        candidate = parts[0].title()
        # Avoid generic all-caps strings that are not very meaningful.
        if len(candidate) >= 3:
            return candidate

    return "Unknown"

