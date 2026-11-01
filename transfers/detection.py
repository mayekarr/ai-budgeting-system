from __future__ import annotations

"""
Inter-account transfer detection (FR-9c/9d/9e).

Tier 1 (signal-based, high confidence): every candidate counterpart must resolve through a
registered AccountAlias or a shared bank reference number — this is the single mechanism that
structurally keeps external parties (a dependent, a tradesperson, a friend paying back a dinner
split) out of Transfer classification, per docs/design-logic-and-ux.md §2.1: they simply never
match an alias, so they're never candidates in the first place, not excluded by a bolted-on
denylist.

Tier 2 (heuristic pairing, J5, docs/design-logic-and-ux.md §2.3): when Tier 1 finds nothing, falls
back to the same amount on another of the user's accounts within a couple of business days. The amount
must match exactly (Rohan, 2026-11-01: a transfer between his own accounts matches to the cent; a
near-equal amount is a coincidence) and neither row may be of a bank type that is never a transfer
(a card purchase, fee, ATM withdrawal, ...) or carry a bank Category that plainly isn't one (Donations,
Refund, Groceries, ...). Two confidence bands:
  - High (same day): auto-tagged Transfer, no review.
  - Medium (within the window): auto-tagged Transfer, but flagged needs_review as a soft confirmation.

A group is always exactly two legs, and a row never joins another row's group. Tier 1 overrides a
Tier-2 group that holds one of its rows (that group is taken apart); it never takes a row from a Tier-1
group.
"""

import re
from datetime import date as date_type, timedelta
from typing import Optional

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from backend.models import Account, AccountAlias, Transaction, TransferGroup
from categorisation.capital_events import capital_event_clause, is_capital_event
from backend.needs_review_reasons import TRANSFER_MATCH, should_supersede
from transfers.aliases import alias_matches_text

_REFERENCE_TOKEN_RE = re.compile(r"\b[A-Za-z]{1,3}\d{6,}\b")
_DATE_WINDOW = timedelta(days=3)

# Tier 2 tunable defaults (docs/design-logic-and-ux.md §2.3/§4) — not locked, revisit with real
# data volume.
_TIER2_BUSINESS_DAY_WINDOW = 2

# Bank transaction types that can never be one leg of a move between the user's own accounts
# (Rohan, 2026-11-01: a transfer is an exact-amount move between his own accounts). Read from the
# real data: every genuine pair is TRANSFER DEBIT / TRANSFER CREDIT, a card payment (AUTOMATIC
# DRAWING on the paying side, CREDIT CARD PAYMENT on the card) or an INTER-BANK CREDIT (his own
# account at another bank); the wrong matches were purchases, fees, ATM cash, reversals, salary and
# interest. A blank type (a statement format that gives none) is allowed.
NON_TRANSFER_BANK_TYPES = frozenset({
    "CREDIT CARD PURCHASE", "PURCHASE AUTHORISATION", "CREDIT CARD REFUND", "FEES", "ATM DEBIT",
    "INTEREST PAID", "INTEREST CHARGED", "SALARY", "DIVIDEND", "REVERSAL CREDIT",
    "MISCELLANEOUS DEBIT", "DEPOSIT",
})


def can_be_transfer_leg(tx: Transaction) -> bool:
    return (tx.raw_transaction_type or "").strip().upper() not in NON_TRANSFER_BANK_TYPES


# The bank's own Category values a transfer leg can carry (Rohan, 2026-11-01: internal transfers say
# "Internal transfers"). Read from the real statements: "Internal transfers" for moves between NAB
# accounts, "Credit card repayments" on the paying side of a card payment, and "Transfers out/in" (with
# "Income", "Investments", "Investment income") for the older statements and for money going to or
# coming from another bank. Anything else (Donations, Refund, Groceries, ...) is plainly not a transfer.
# The label is over-inclusive (it also covers other people's NAB accounts), so it can rule a pairing out
# but never prove one. A row with no category (a format without the column) is allowed.
TRANSFER_LIKE_BANK_CATEGORIES = frozenset({
    "internal transfers", "transfers in", "transfers out", "credit card repayments",
    "investments", "investment income", "income",
})


def bank_category_allows_transfer(tx: Transaction) -> bool:
    category = (tx.raw_bank_category or "").strip().lower()
    return not category or category in TRANSFER_LIKE_BANK_CATEGORIES


# Income that is a deliberate, confident classification and must never be paired with another row on
# amount/date coincidence alone: the ATO tax-refund exception (§4.2) and rent (a $653.67 rent credit
# was once paired with a -$651.03 Medibank debit).
_NEVER_HEURISTIC_SUBCATEGORIES = ("Tax Refund", "Rental Income")


def is_never_transfer(tx: Transaction) -> bool:
    """A confident classification (ATO refund, rent, a capital event) that no transfer match may overwrite."""
    if tx.category == "Income" and tx.subcategory in _NEVER_HEURISTIC_SUBCATEGORIES:
        return True
    return is_capital_event(tx.category, tx.subcategory)


def _find_account_via_alias_in_text(session: Session, text: str, exclude_account_id: int) -> Optional[int]:
    aliases = session.query(AccountAlias).filter(AccountAlias.account_id != exclude_account_id).all()
    for alias in aliases:
        if alias_matches_text(alias.raw_identifier, text):
            return alias.account_id
    return None


def _reference_tokens(text: str) -> list[str]:
    return _REFERENCE_TOKEN_RE.findall(text)


def _is_available(candidate: Transaction) -> bool:
    """
    Free for a Tier-1 link: a live row of a transfer-capable bank type that is ungrouped or sits only
    in a weaker (Tier-2, amount-and-date) group, which an account-number or reference match overrides.
    A row already in a Tier-1 group is taken.
    """
    if candidate.superseded_by_id is not None or not can_be_transfer_leg(candidate):
        return False
    group = candidate.transfer_group
    return group is None or group.detection_tier >= 2


def _find_counterpart_via_reference_number(session: Session, tx: Transaction) -> Optional[Transaction]:
    for token in _reference_tokens(tx.raw_description):
        candidates = (
            session.query(Transaction)
            .filter(
                Transaction.id != tx.id,
                Transaction.account_id != tx.account_id,
                Transaction.raw_description.contains(token),
                Transaction.amount == -tx.amount,  # opposite sign, same magnitude: the same transfer
            )
            .all()
        )
        available = [c for c in candidates if _is_available(c)]
        if available:
            # Prefer a free row over one that has to be taken back from a Tier-2 pairing.
            return min(available, key=lambda c: (c.transfer_group_id is not None, c.id))
    return None


def _find_counterpart_via_alias(session: Session, tx: Transaction) -> Optional[Transaction]:
    other_account_id = _find_account_via_alias_in_text(session, tx.raw_description, exclude_account_id=tx.account_id)
    if other_account_id is None:
        return None

    window_start = tx.date - _DATE_WINDOW
    window_end = tx.date + _DATE_WINDOW
    candidates = (
        session.query(Transaction)
        .filter(
            Transaction.id != tx.id,
            Transaction.account_id == other_account_id,
            # Opposite sign AND exactly the same amount: transfers match to the cent.
            Transaction.amount == -tx.amount,
            Transaction.date >= window_start,
            Transaction.date <= window_end,
        )
        .all()
    )
    available = [c for c in candidates if _is_available(c)]
    if not available:
        return None
    # When more than one candidate matches (two genuinely separate transfers of the same amount
    # between the same two accounts, a few days apart) the closest date is almost always the true
    # pair; a free row beats one that would have to be taken back from a Tier-2 pairing.
    return min(available, key=lambda c: (c.transfer_group_id is not None, abs((c.date - tx.date).days), c.id))


def _dissolve_group(session: Session, group: TransferGroup, keep: tuple[Transaction, ...]) -> None:
    """
    Take a weaker (Tier-2) group apart because a stronger match claimed one of its rows. Every other
    member goes back to an ordinary Income/Expense row (it was only ever paired on amount and date).
    """
    for member in list(group.members):
        member.transfer_group = None
        if member not in keep:
            member.type = "Income" if member.amount > 0 else "Expense"
            if member.needs_review_reason == TRANSFER_MATCH:
                member.needs_review = False
                member.needs_review_reason = None
    session.flush()
    session.delete(group)
    session.flush()


def link_transfer_pair(
    session: Session, tx: Transaction, counterpart: Transaction, tier: int, confidence: float = 1.0
) -> bool:
    """
    Links two transactions as a Transfer: one TransferGroup of exactly two legs, both typed
    `type=Transfer`. A row never joins somebody else's group (that is how a shop purchase ended up
    attached to a real transfer): if either row already sits in a group that is as strong or stronger
    than this link (`detection_tier` <= `tier`), nothing is linked and False is returned. A Tier-1 link
    (account number or reference) overrides a Tier-2 group (amount and date only): that group is taken
    apart and its other rows go back to ordinary income/expense.

    Public: also used by backend/api.py's manual confirm_transfer_with_id action.

    Also clears a pre-existing needs_review flag that this link makes moot (docs/design-logic-and-ux.md
    §2.3: a confident match "auto-links with no review"). unrecognised_account is never cleared: it is
    about the account's identity, not this transaction's classification. A Tier-1 link also clears the
    old category, which means nothing on a final Transfer; a Tier-2 link keeps it, because a stronger
    match (or a rejection) can still send the row back to being income or spending.

    Medium-band note: `_process_tier2` calls `_flag_transfer_match(..., type_changed=True)` straight
    after this, which re-flags `needs_review`/`TRANSFER_MATCH`; do not separate those two calls.
    """
    if tx.transfer_group_id is not None and tx.transfer_group_id == counterpart.transfer_group_id:
        return True
    for member in (tx, counterpart):
        group = member.transfer_group
        if group is None:
            continue
        if group.detection_tier <= tier:
            return False
        _dissolve_group(session, group, keep=(tx, counterpart))

    group = TransferGroup(detection_tier=tier, confidence=confidence)
    session.add(group)
    session.flush()

    tx.transfer_group = group
    counterpart.transfer_group = group
    tx.type = "Transfer"
    counterpart.type = "Transfer"

    for member in (tx, counterpart):
        if tier == 1:
            member.category = None
            member.subcategory = None
        if member.needs_review_reason is None or should_supersede(member.needs_review_reason, TRANSFER_MATCH):
            member.needs_review = False
            member.needs_review_reason = None

    session.commit()
    return True


def _add_business_days(d: date_type, n: int) -> date_type:
    step = 1 if n > 0 else -1
    remaining = abs(n)
    while remaining > 0:
        d += timedelta(days=step)
        if d.weekday() < 5:  # Mon-Fri
            remaining -= 1
    return d


def _amounts_exact_opposite(a: float, b: float) -> bool:
    return a == -b


def _tier2_band(tx_date: date_type, candidate_date: date_type) -> str:
    """Amounts always match exactly by now: same day is High, within the window is Medium."""
    return "high" if tx_date == candidate_date else "medium"


def _find_tier2_candidates(session: Session, tx: Transaction) -> list[tuple[Transaction, str]]:
    """Every opposite-sign, near-equal-amount, in-window candidate on a different account, each
    tagged with its confidence band (§2.3). §2.1's candidate-pool restriction is automatically
    satisfied — every Transaction is FK'd to a real Account, so no alias check is needed here."""
    window_start = _add_business_days(tx.date, -_TIER2_BUSINESS_DAY_WINDOW)
    window_end = _add_business_days(tx.date, _TIER2_BUSINESS_DAY_WINDOW)
    rows = (
        session.query(Transaction)
        .filter(
            Transaction.id != tx.id,
            Transaction.account_id != tx.account_id,
            Transaction.date >= window_start,
            Transaction.date <= window_end,
            # A superseded PENDING row (backend/database.py's pending<->settled reconciliation) is
            # a shadow of its SETTLED counterpart, not a second real transaction — matching against
            # it would risk transfer-tagging a row that rollups already exclude, for a real-world
            # charge only the settled row represents.
            Transaction.superseded_by_id.is_(None),
            # A groupless Transfer is already resolved (a loan drawdown/paydown typed from its
            # text, transfers/loan_movements.py), so it is never a heuristic partner.
            Transaction.type != "Transfer",
            # A candidate already linked into some other TransferGroup must not be pulled into a
            # new, unrelated one on pure amount/date coincidence — Tier 2 only ever proposes a
            # link between two rows that are BOTH still unresolved. (`tx` itself is guaranteed
            # unlinked here too: process_transfer_detection already returns early for
            # type=="Transfer".) Mirrors the same guard backend/api.py's manual
            # confirm_transfer_with_id action applies.
            Transaction.transfer_group_id.is_(None),
            # The ATO tax-refund override (§4.2's scoped exception) is a deliberate, confident
            # classification — a coincidental opposite-amount/same-day match on another account
            # must never be allowed to reclassify it as a Transfer via pure heuristic coincidence,
            # same reasoning the upload handler already applies when deciding whether to run
            # detection on the ATO row itself (backend/api.py). Enforced here too so a match
            # approaching from the *other* side (this row is the one being searched on) can't
            # sneak the ATO row in as someone else's counterpart.
            # coalesce(...) avoids SQL's three-valued-logic trap: category/subcategory are
            # nullable, and `~and_(category == 'Income', ...)` evaluates to NULL (not TRUE) for a
            # row with a NULL category — which a WHERE clause silently drops, wrongly excluding
            # every plain uncategorised row instead of only the ATO ones.
            ~or_(
                and_(
                    func.coalesce(Transaction.category, "") == "Income",
                    func.coalesce(Transaction.subcategory, "").in_(_NEVER_HEURISTIC_SUBCATEGORIES),
                ),
                capital_event_clause(),
            ),
        )
        .all()
    )
    candidates = []
    for row in rows:
        if (
            not _amounts_exact_opposite(tx.amount, row.amount)
            or not can_be_transfer_leg(row)
            or not bank_category_allows_transfer(row)
        ):
            continue
        candidates.append((row, _tier2_band(tx.date, row.date)))
    return candidates


_BAND_RANK = {"high": 2, "medium": 1}


def _tier2_score(tx: Transaction, pair: tuple[Transaction, str]) -> tuple[int, int]:
    candidate, band = pair
    return (_BAND_RANK[band], -abs((candidate.date - tx.date).days))


def _tie_is_interchangeable(session: Session, tx: Transaction, candidates: list[Transaction]) -> bool:
    """
    A tie costs nothing when the candidates are indistinguishable from each other (one account, one
    date) and as many identical rows are waiting on this side as there are candidates: then a perfect
    pairing exists and any assignment is as right as any other. One debit against two identical
    credits is NOT such a tie (one credit is not this transfer), nor is a tie across accounts.
    """
    if len({c.account_id for c in candidates}) != 1 or len({c.date for c in candidates}) != 1:
        return False
    equivalents = (
        session.query(Transaction)
        .filter(
            Transaction.account_id == tx.account_id,
            Transaction.date == tx.date,
            Transaction.amount == tx.amount,
            Transaction.superseded_by_id.is_(None),
            Transaction.transfer_group_id.is_(None),
            Transaction.type != "Transfer",
        )
        .all()
    )
    equivalents = [e for e in equivalents if can_be_transfer_leg(e) and bank_category_allows_transfer(e)]
    return len(equivalents) == len(candidates)


def _best_tier2_candidate(
    session: Session, tx: Transaction
) -> Optional[tuple[Transaction, str, list[Transaction]]]:
    """Returns (best candidate, band, other candidates that tied for best) — the tied-but-not-
    chosen list lets the caller flag them too rather than letting a genuine multi-way ambiguity
    silently vanish once the winner consumes the only pairing (/code-review finding)."""
    candidates = _find_tier2_candidates(session, tx)
    if not candidates:
        return None

    scored = [(pair, _tier2_score(tx, pair)) for pair in candidates]
    best_score = max(score for _, score in scored)
    tied = [pair for pair, score in scored if score == best_score]
    candidate, band = tied[0]
    other_tied = [c for c, _ in tied[1:]]

    # Two identical $5,000 payments to a card on the same day against two identical $5,000 credits:
    # every pairing is equally right, so there is nothing to flag and nothing to downgrade.
    if len(tied) > 1 and _tie_is_interchangeable(session, tx, [c for c, _ in tied]):
        return candidate, band, []

    # A genuine tie (e.g. two same-amount, same-day candidates on different accounts) must not be
    # silently auto-linked to whichever the DB happens to return first — High confidence claims
    # certainty a tie doesn't have. Downgrade to Medium so it's auto-linked but still surfaced for
    # confirmation, rather than picking an arbitrary winner with zero review flag.
    if len(tied) > 1 and band == "high":
        band = "medium"
    return candidate, band, other_tied


_TIER2_MEDIUM_CONFIDENCE = 0.6


def _flag_unresolved_tie_losers(others: list[Transaction]) -> None:
    """A candidate that tied for the best match but lost the pairing to another candidate must not
    vanish with zero signal once the winner is linked/flagged — flag it too (unlinked) so a
    genuine multi-way ambiguity stays visible in the review queue (/code-review finding)."""
    for other in others:
        other.needs_review = True
        if other.needs_review_reason is None or should_supersede(other.needs_review_reason, TRANSFER_MATCH):
            other.needs_review_reason = TRANSFER_MATCH


def _process_tier2(session: Session, tx: Transaction) -> None:
    if is_never_transfer(tx) or not can_be_transfer_leg(tx) or not bank_category_allows_transfer(tx):
        return
    found = _best_tier2_candidate(session, tx)
    if found is None:
        return
    candidate, band, other_tied = found

    if band == "high":
        link_transfer_pair(session, tx, candidate, tier=2, confidence=1.0)
        return

    if link_transfer_pair(session, tx, candidate, tier=2, confidence=_TIER2_MEDIUM_CONFIDENCE):
        _flag_transfer_match(tx, candidate, type_changed=True)
        _flag_unresolved_tie_losers(other_tied)
        session.commit()


def _flag_transfer_match(tx: Transaction, candidate: Transaction, *, type_changed: bool) -> None:
    """
    Flags both rows needs_review. An already-stored reason is only ever superseded per the shared
    precedence table in backend/needs_review_reasons.py (should_supersede) — and even then, ONLY
    when this match actually changed `type` to Transfer (type_changed=True, i.e. the Medium band;
    High never reaches here — see the known, documented gap in docs/next-steps.md). Once a row is
    genuinely re-typed Transfer, its category/refund status stops mattering for any reporting view
    (GET /summary excludes type=Transfer outright), so superseding those two is both safe and
    necessary: without it, the Needs-Review page (which dispatches purely on needs_review_reason)
    would never surface the new link for confirmation, while resolving the stale reason (e.g.
    saving a category correction) would clear needs_review and silently strand the transaction as
    an unreviewed Transfer (/code-review finding). unrecognised_account outranks transfer_match in
    that table, so it's never superseded either way — it's about the account's identity, not this
    transaction's classification, and (per ingestion/account_resolution.py) is only ever raised
    once per account, so losing it here would mean losing it for good. For a Low-band match
    (type_changed=False), nothing about the row's classification changed, so an existing reason —
    including a "lesser" one like low_confidence_category — is left exactly as live as before.
    """
    for member in (tx, candidate):
        member.needs_review = True
        if member.needs_review_reason is None or (
            type_changed and should_supersede(member.needs_review_reason, TRANSFER_MATCH)
        ):
            member.needs_review_reason = TRANSFER_MATCH


def process_transfer_detection(session: Session, tx: Transaction, tiers: tuple[int, ...] = (1, 2)) -> None:
    """
    Run transfer detection for one transaction: Tier 1 (account number or shared reference) first,
    then Tier 2 (the same exact amount on another account within a couple of business days). `tiers`
    lets a caller run the passes separately over a whole batch (all of Tier 1, then all of Tier 2) so
    the order the rows arrive in cannot let an amount-only match take a row from a reference match.
    Leaves `type` untouched when neither tier finds a match, and never touches a row whose bank type
    says it is a purchase, fee, cash withdrawal and so on.
    """
    if tx.type == "Transfer":
        return  # already linked
    if not can_be_transfer_leg(tx):
        return

    if 1 in tiers:
        counterpart = _find_counterpart_via_reference_number(session, tx)
        if counterpart is None:
            counterpart = _find_counterpart_via_alias(session, tx)
        if counterpart is not None and link_transfer_pair(session, tx, counterpart, tier=1):
            return

    if 2 in tiers:
        _process_tier2(session, tx)


def find_suggested_transfer_match(session: Session, tx: Transaction) -> Optional[Transaction]:
    """
    Recompute the current best Tier-2 candidate (same exact amount, opposite sign, another account)
    for a transaction flagged needs_review with reason=transfer_match but not yet linked, for the
    review-queue API to show a suggested counterpart without persisting an unconfirmed link.
    """
    if not can_be_transfer_leg(tx) or not bank_category_allows_transfer(tx):
        return None
    found = _best_tier2_candidate(session, tx)
    return found[0] if found else None


