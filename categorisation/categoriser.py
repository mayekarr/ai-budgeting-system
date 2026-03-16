from __future__ import annotations

import logging
from typing import Dict

logger = logging.getLogger(__name__)

# Canonical mapping of merchant -> category.
MERCHANT_CATEGORY_MAP: Dict[str, str] = {
    "Uber": "Transport",
    "Woolworths": "Groceries",
    "Netflix": "Entertainment",
    "Amazon": "Shopping",
}


def categorise_merchant(merchant: str) -> str:
    """
    Map a merchant name to a spending category using simple rules.

    Known mappings:
        Uber        -> Transport
        Woolworths  -> Groceries
        Netflix     -> Entertainment
        Amazon      -> Shopping

    Fallback category is "Other".
    """
    if not merchant:
        logger.debug("Categoriser received empty merchant; defaulting to 'Other'.")
        return "Other"

    # Try to normalize merchant key for matching.
    normalized = merchant.strip()

    # Exact match first
    if normalized in MERCHANT_CATEGORY_MAP:
        category = MERCHANT_CATEGORY_MAP[normalized]
        logger.debug("Categoriser matched merchant '%s' to category '%s'.", normalized, category)
        return category

    # Case-insensitive match
    for key, value in MERCHANT_CATEGORY_MAP.items():
        if key.lower() == normalized.lower():
            logger.debug(
                "Categoriser matched merchant '%s' (case-insensitive) to category '%s'.",
                normalized,
                value,
            )
            return value

    logger.info("Categoriser did not find a mapping for merchant '%s'; using 'Other'.", merchant)
    return "Other"

