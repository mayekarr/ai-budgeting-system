from __future__ import annotations

"""
The project's one canonical way to match a registered AccountAlias against free text — shared by
transfer detection (transfers/detection.py) and refund counterparty resolution
(transfers/refunds.py) so the two can't silently diverge on what "this text names a known account"
means.
"""

import re

_MASKING_RUN_RE = re.compile(r"[xX]{3,}")
_NEVER_MATCHES = re.compile(r"(?!)")  # a regex that cannot match any string


def alias_pattern(raw_identifier: str) -> re.Pattern:
    """
    Build a search pattern for an alias, treating a RUN of 3+ 'x' characters (bank masking, e.g.
    "453030xxxxxx7128", 6 in a row) as digit wildcards. A single incidental 'x' — an institution
    name like "AMEX", an account nickname — is not masking and must stay literal; only a long run
    is the real signal, per the actual masking pattern observed in §4.1's real data.

    An alias that is masking characters *only* (no literal digits at all, e.g. a fully-redacted
    "xxxxxx" some export formats could in principle provide) carries zero identifying signal — it
    must never degenerate into a wildcard that matches everything, so it's treated as unusable
    (matches nothing) rather than as a pattern that would falsely match every transaction.
    """
    if _MASKING_RUN_RE.search(raw_identifier):
        parts = _MASKING_RUN_RE.split(raw_identifier)
        if not any(p.strip() for p in parts):
            return _NEVER_MATCHES
        pattern = r"\d*".join(re.escape(p) for p in parts)
        return re.compile(pattern, re.IGNORECASE)
    return re.compile(re.escape(raw_identifier), re.IGNORECASE)


def alias_matches_text(raw_identifier: str, text: str) -> bool:
    return alias_pattern(raw_identifier).search(text) is not None
