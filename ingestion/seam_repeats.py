from __future__ import annotations

"""
Removes the duplicated blocks the bank's export tool writes at its 1,000-row page seams.

Found in the real CC export (docs/product-requirements.md FR-9k): at rows 2000/3000/…/6000 the file
re-lists the rows that ended the previous page *immediately after* the seam (92 rows in the real
data), so the dates jump out of order there. Rohan confirmed against the bank's own statement that
the repeats are not real transactions.

A single matching row can't tell a fake repeat from a genuine second identical purchase on the same
day, so this only acts on a whole block: at a point where date order breaks, the `k` rows just
before it must match the `k` rows just after it, verbatim and in order, with `k >= MIN_BLOCK`.
Genuine repeat purchases are a handful of rows apart and don't break date order, so they never
qualify. Anything ambiguous (a near-miss block, no order break) is kept: a visible duplicate costs
less than a lost real transaction.

The running balance is deliberately not part of the match -- the export computes it over the
stitched rows, so the copy carries different balances. For the same reason the surviving balances
are recomputed after a drop (see `_recompute_balances`).
"""

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ingestion.nab_format import ParsedRow

logger = logging.getLogger(__name__)

# Genuine identical runs are a few rows long at most; a page-seam repeat is ~90. Anything below
# this is treated as real data.
MIN_BLOCK = 10


def _key(row: "ParsedRow") -> tuple:
    return (row.date, row.amount, row.account_identifier, row.raw_transaction_type, row.raw_description)


def drop_seam_repeats(rows: list["ParsedRow"]) -> tuple[list["ParsedRow"], list["ParsedRow"]]:
    """Return `(kept, dropped)`, preserving file order. `dropped` is the repeated copies."""
    n = len(rows)
    if n < 2 * MIN_BLOCK:
        return list(rows), []

    span = (rows[-1].date - rows[0].date).days
    if span == 0:
        return list(rows), []
    direction = 1 if span > 0 else -1  # +1 oldest-first, -1 newest-first

    keys = [_key(r) for r in rows]
    drop = [False] * n
    blocks = 0
    seam = 1
    while seam < n:
        broke_order = (rows[seam].date - rows[seam - 1].date).days * direction < 0
        block = _repeated_block_length(keys, seam) if broke_order else 0
        if block:
            for i in range(seam, seam + block):
                drop[i] = True
            blocks += 1
            seam += block
        else:
            seam += 1

    kept = [r for r, d in zip(rows, drop) if not d]
    dropped = [r for r, d in zip(rows, drop) if d]
    if dropped:
        logger.warning("Dropped %d export-seam repeat row(s) in %d block(s)", len(dropped), blocks)
        kept = _recompute_balances(rows, drop, newest_last=direction > 0)
    return kept, dropped


def _recompute_balances(rows: list["ParsedRow"], drop: list[bool], *, newest_last: bool) -> list["ParsedRow"]:
    """
    Return the kept rows with balances rebuilt backward from the newest row.

    The export computes its Balance column over the stitched rows, so after dropping the copies the
    surviving balances are wrong (checked against the bank's own statements, FR-9k). The newest
    row's balance is the one value known to be right. Two guards keep this from overwriting good
    data: the rows the fault cannot have touched (newest end, before the first drop) must chain
    (`balance - amount == next balance`), otherwise the file's convention isn't what this assumes;
    and a row the bank gave no balance for stays without one.
    """
    order = list(range(len(rows)))
    if newest_last:
        order.reverse()  # newest first
    # A dropped row's balance came from the stitched rows and is wrong, so anchor on the newest
    # row that survives.
    while drop[order[0]]:
        order.pop(0)
    anchor = rows[order[0]].balance
    if anchor is None or not _newest_end_chains(rows, drop, order):
        return [r for r, d in zip(rows, drop) if not d]

    balance = anchor
    rebuilt: dict[int, "ParsedRow"] = {}
    for i in order:
        if drop[i]:
            continue
        row = rows[i]
        rebuilt[i] = row if row.balance is None else replace(row, balance=round(balance, 2))
        balance -= row.amount
    return [rebuilt[i] for i in sorted(rebuilt)]


def _newest_end_chains(rows: list["ParsedRow"], drop: list[bool], order: list[int]) -> bool:
    untouched = []
    for i in order:
        if drop[i]:
            break
        untouched.append(rows[i])
    for newer, older in zip(untouched, untouched[1:]):
        if newer.balance is None or older.balance is None:
            continue
        if abs((newer.balance - newer.amount) - older.balance) > 0.005:
            return False
    return True


def _repeated_block_length(keys: list[tuple], seam: int) -> int:
    """Longest `k >= MIN_BLOCK` with keys[seam-k:seam] == keys[seam:seam+k], else 0."""
    first = keys[seam]
    for k in range(min(seam, len(keys) - seam), MIN_BLOCK - 1, -1):
        # The copy starts with the same row the block started with; reject cheaply before slicing.
        if keys[seam - k] == first and keys[seam - k : seam] == keys[seam : seam + k]:
            return k
    return 0
