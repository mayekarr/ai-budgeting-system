from __future__ import annotations

from datetime import date as date_type
from typing import Generator, List, Optional

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlalchemy.orm import Session

from categorisation.claude_fallback import categorise_with_fallback
from categorisation.rules import match_rule
from categorisation.seed_rules import seed_rules_if_empty
from categorisation.taxonomy import is_valid_category
from ingestion.account_resolution import resolve_account
from ingestion.nab_format import NabFormatError, parse_nab_format
from transfers.detection import find_suggested_transfer_match, process_transfer_detection
from transfers.refunds import detect_refund

from .database import SessionLocal, bulk_save_transactions, create_tables, engine  # noqa: F401  (engine kept for test monkeypatching)
from .models import CategorisationRule, Transaction, TransferGroup
from .needs_review_reasons import (
    LOW_CONFIDENCE_CATEGORY,
    REFUND_AMBIGUITY,
    TRANSFER_MATCH,
    UNRECOGNISED_ACCOUNT,
)

# Below any real seeded/llm_promoted rule priority (categorisation/seed_rules.py starts at 1;
# claude_fallback.py promotes at 500) — an explicit user correction (FR-9) must win a same-text
# exact-match tie over anything automatic.
USER_CORRECTION_RULE_PRIORITY = 0

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("FastAPI startup: initialising database tables.")
    create_tables()
    with SessionLocal() as db:
        seeded = seed_rules_if_empty(db)
        if seeded:
            logger.info("Seeded %d starter categorisation rules from Source 1.", seeded)
    yield


app = FastAPI(title="AI Personal Budgeting and Expense Categorisation System", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For local MVP; tighten in production.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    date: date_type
    amount: float
    raw_description: str
    merchant: str | None
    category: str | None
    subcategory: str | None
    type: str
    is_refund: bool
    transfer_group_id: int | None
    superseded_by_id: int | None
    source: str
    needs_review: bool
    needs_review_reason: str | None
    confidence_score: float | None


class TransactionCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Category correction (J4) — category, if given, must come with a valid subcategory pairing.
    category: str | None = None
    subcategory: str | None = None
    # Refund-ambiguity resolution (J5, §1.2): user confirms/corrects an is_refund flag.
    is_refund: bool | None = None
    # Transfer-match resolution (J5, §2.3/§3.2):
    #   - confirm_transfer_match: the transaction is already linked (Tier-2 Medium's soft
    #     confirmation) — just clear the review flag on every leg of its group.
    #   - confirm_transfer_with_id: the transaction is NOT yet linked (Tier-2 Low's suggested-only
    #     match) — link it now with the given counterpart, confidently, then clear the flag.
    #   - reject_transfer_match: "not a transfer" — unlink if linked (reverting `type` to what the
    #     amount sign implies) and always clear the review flag.
    confirm_transfer_match: bool = False
    confirm_transfer_with_id: int | None = None
    reject_transfer_match: bool = False


class UploadResult(BaseModel):
    message: str
    count: int
    needs_review_count: int


class CategorySummary(BaseModel):
    category: str
    amount: float


class SummaryOut(BaseModel):
    date_from: date_type | None
    date_to: date_type | None
    total_income: float
    total_expense: float
    net: float
    by_category: List[CategorySummary]


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency; reads SessionLocal from this module so tests can swap it out."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.post("/transactions/upload", status_code=status.HTTP_201_CREATED, response_model=UploadResult)
async def upload_transactions(
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
) -> UploadResult:
    """
    Upload a NAB-style bank statement. Parses, resolves the account, categorises (rule then Claude
    API fallback), detects transfers/refunds, and persists — skipping duplicates (FR-3).
    """
    logger.info("Received upload request: filename=%s", file.filename)
    try:
        contents = await file.read()
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Unable to read uploaded file.")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unable to read uploaded file: {exc}") from exc

    try:
        parsed_rows = parse_nab_format(contents, filename=file.filename)
    except NabFormatError as exc:
        logger.warning("NAB format parse error: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    to_persist = []
    for row in parsed_rows:
        resolved = resolve_account(db, row.account_identifier)

        rule_match = match_rule(db, row.raw_description)
        if rule_match is not None:
            category, subcategory, confidence, cat_needs_review = (
                rule_match.category, rule_match.subcategory, rule_match.confidence, False,
            )
        else:
            fallback = categorise_with_fallback(db, row.raw_description)
            category, subcategory, confidence, cat_needs_review = (
                fallback.category, fallback.subcategory, fallback.confidence, fallback.needs_review,
            )

        refund_decision = detect_refund(
            db,
            raw_description=row.raw_description,
            amount=row.amount,
            raw_transaction_type=row.raw_transaction_type,
            bank_category=row.raw_bank_category,
        )

        tx_type = "Income" if row.amount > 0 else "Expense"
        if refund_decision.route_to_income:
            # The override replaces whatever categorisation produced — including its confidence —
            # with a confident, deterministic value. Any earlier low-confidence flag on the
            # now-discarded category no longer applies; only detect_refund's own signals (always
            # False for this path) and account resolution still matter.
            category, subcategory = "Income", "Tax Refund"
            tx_type = "Income"
            cat_needs_review = False

        # Priority when more than one signal is ambiguous at once: an unrecognised account is the
        # most foundational concern (it affects what the row even *means*), then refund ambiguity,
        # then a merely-low-confidence category — matching backend/needs_review_reasons.py.
        if resolved.needs_review:
            needs_review_reason = UNRECOGNISED_ACCOUNT
        elif refund_decision.needs_review:
            needs_review_reason = REFUND_AMBIGUITY
        elif cat_needs_review:
            needs_review_reason = LOW_CONFIDENCE_CATEGORY
        else:
            needs_review_reason = None

        to_persist.append(
            {
                "account_id": resolved.account.id,
                "date": row.date,
                "amount": row.amount,
                "raw_description": row.raw_description,
                "merchant": None,
                "category": category,
                "subcategory": subcategory,
                "type": tx_type,
                "is_refund": refund_decision.is_refund,
                "source": "bank_import",
                "needs_review": needs_review_reason is not None,
                "needs_review_reason": needs_review_reason,
                "confidence_score": confidence,
                "raw_transaction_type": row.raw_transaction_type,
                "balance": row.balance,
            }
        )

    try:
        saved_rows = bulk_save_transactions(db, to_persist)
        db.commit()
    except Exception as exc:  # pylint: disable=broad-except
        db.rollback()
        logger.exception("Failed to save imported transactions.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to save transactions: {exc}"
        ) from exc

    # Transfer detection needs persisted rows (it searches other Transaction rows), so it runs
    # as a second pass over exactly what this call actually inserted — not a count-based query,
    # which would pull in unrelated older rows whenever this upload contained duplicates (the
    # normal FR-3 re-upload case, where fewer rows are saved than were parsed). ATO-override rows
    # are excluded too: they're a deliberate, confident classification, and a coincidental
    # amount/date match against an unrelated transaction on another account must not be allowed
    # to overwrite it into a Transfer.
    for tx in saved_rows:
        is_ato_override = tx.category == "Income" and tx.subcategory == "Tax Refund"
        if tx.type != "Transfer" and not is_ato_override:
            process_transfer_detection(db, tx)

    # Reflects only this upload's rows, not every needs-review row ever persisted — a global
    # count would misreport every upload after the first.
    needs_review_count = sum(1 for tx in saved_rows if tx.needs_review)

    logger.info("Upload complete: %d saved, %d flagged for review.", len(saved_rows), needs_review_count)
    return UploadResult(
        message="Transactions imported successfully.",
        count=len(saved_rows),
        needs_review_count=needs_review_count,
    )


@app.get("/transactions", response_model=List[TransactionOut])
def list_transactions(
    db: Session = Depends(get_session),
    date_from: Optional[date_type] = Query(default=None),
    date_to: Optional[date_type] = Query(default=None),
    account_id: Optional[int] = Query(default=None),
    category: Optional[str] = Query(default=None),
    type: Optional[str] = Query(default=None),
    needs_review: Optional[bool] = Query(default=None),
    needs_review_reason: Optional[str] = Query(default=None),
    transfer_group_id: Optional[int] = Query(default=None),
) -> List[TransactionOut]:
    """
    Filterable transaction list (FR-13/FR-14; needs_review backs FR-10's review queue).
    needs_review_reason and transfer_group_id back J5's Needs-Review page — the latter is what
    lets the Transfers part of that queue fetch every leg of a suggested/confirmed group in one
    call (docs/design-logic-and-ux.md §2.4).
    """
    q = db.query(Transaction)
    if date_from is not None:
        q = q.filter(Transaction.date >= date_from)
    if date_to is not None:
        q = q.filter(Transaction.date <= date_to)
    if account_id is not None:
        q = q.filter(Transaction.account_id == account_id)
    if category is not None:
        q = q.filter(Transaction.category == category)
    if type is not None:
        q = q.filter(Transaction.type == type)
    if needs_review is not None:
        q = q.filter(Transaction.needs_review.is_(needs_review))
    if needs_review_reason is not None:
        q = q.filter(Transaction.needs_review_reason == needs_review_reason)
    if transfer_group_id is not None:
        q = q.filter(Transaction.transfer_group_id == transfer_group_id)

    records = q.order_by(Transaction.date.desc(), Transaction.id.desc()).all()
    logger.info("Fetched %d transactions.", len(records))
    return records


@app.get("/transactions/{transaction_id}/suggested-transfer-match", response_model=Optional[TransactionOut])
def get_suggested_transfer_match(
    transaction_id: int,
    db: Session = Depends(get_session),
) -> Optional[Transaction]:
    """
    The current best Tier-2 Low-confidence candidate for a not-yet-linked
    needs_review_reason=transfer_match row (docs/design-logic-and-ux.md §2.3) — recomputed on
    request rather than persisted, since a Low match is deliberately never auto-tagged. Backs J5's
    Needs-Review page. Returns null (not 404) when there's currently no candidate, since "no
    suggestion right now" isn't an error — a `confidence_score` of 1.0 on the caller's own read is
    NOT implied here; this is a suggestion, not a scored field on the transaction itself.
    """
    tx = db.get(Transaction, transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found.")
    return find_suggested_transfer_match(db, tx)


@app.patch("/transactions/{transaction_id}", response_model=TransactionOut)
def correct_transaction(
    transaction_id: int,
    correction: TransactionCorrection,
    db: Session = Depends(get_session),
) -> Transaction:
    """
    Manual category correction (J4, FR-9/FR-15), plus J5's review-queue resolution actions
    (is_refund correction, transfer-match confirm/reject). Each action below is independent —
    a request may include one or several at once.
    """
    tx = db.get(Transaction, transaction_id)
    if tx is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found.")

    no_action_requested = (
        correction.category is None
        and correction.is_refund is None
        and not correction.confirm_transfer_match
        and correction.confirm_transfer_with_id is None
        and not correction.reject_transfer_match
    )
    if no_action_requested:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No correction action specified.",
        )

    if correction.category is not None:
        _apply_category_correction(db, tx, correction.category, correction.subcategory)
    if correction.is_refund is not None:
        tx.is_refund = correction.is_refund
        tx.needs_review = False
        tx.needs_review_reason = None
    if correction.confirm_transfer_match:
        _confirm_transfer_match(tx)
    if correction.confirm_transfer_with_id is not None:
        _confirm_transfer_with_id(db, tx, correction.confirm_transfer_with_id)
    if correction.reject_transfer_match:
        _reject_transfer_match(db, tx)

    db.commit()
    db.refresh(tx)
    logger.info("Updated transaction %d.", transaction_id)
    return tx


def _apply_category_correction(db: Session, tx: Transaction, category: str, subcategory: Optional[str]) -> None:
    """
    Writes/updates a `source=user_correction` CategorisationRule keyed on the transaction's exact
    raw_description, so a future transaction with the same text auto-categorises the same way
    instead of repeating the same mistake — the same learning mechanism claude_fallback.py uses
    for a confident LLM result.
    """
    if not is_valid_category(category, subcategory):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid category/subcategory: {category}/{subcategory}",
        )

    tx.category = category
    tx.subcategory = subcategory
    tx.needs_review = False
    tx.needs_review_reason = None
    tx.confidence_score = 1.0

    # Case-insensitive, trimmed comparison — matches categorisation/rules.py's own exact-match
    # semantics (pattern_matches), so two corrections whose raw_description differs only by case
    # or surrounding whitespace are recognised as the same rule instead of creating duplicates.
    # Known, deliberately-unhandled race: this find-or-create isn't transactionally safe against a
    # second PATCH for the same raw_description arriving before this one commits (no unique
    # constraint on pattern/match_type/source) — both would insert. Not worth the added complexity
    # for a single local user driving one correction at a time through the dashboard (NFR-1); revisit
    # if this ever gets a second concurrent caller.
    rule = (
        db.query(CategorisationRule)
        .filter(
            func.upper(func.trim(CategorisationRule.pattern)) == tx.raw_description.strip().upper(),
            CategorisationRule.match_type == "exact",
            CategorisationRule.source == "user_correction",
        )
        .first()
    )
    if rule is None:
        rule = CategorisationRule(
            pattern=tx.raw_description,
            match_type="exact",
            priority=USER_CORRECTION_RULE_PRIORITY,
            source="user_correction",
            is_active=True,
        )
        db.add(rule)
    rule.category = category
    rule.subcategory = subcategory
    logger.info("Corrected transaction %d to %s/%s; user_correction rule updated.",
                tx.id, category, subcategory)


def _confirm_transfer_match(tx: Transaction) -> None:
    """Tier-2 Medium: already linked (auto-tagged) — just clear the soft-confirmation flag on
    every leg of the group together (docs/design-logic-and-ux.md §3.2)."""
    if tx.transfer_group_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transaction has no transfer match to confirm.",
        )
    for member in tx.transfer_group.members:
        member.needs_review = False
        member.needs_review_reason = None


def _confirm_transfer_with_id(db: Session, tx: Transaction, counterpart_id: int) -> None:
    """Tier-2 Low: not yet linked (suggestion only) — link now with the given counterpart at full
    (user-confirmed) confidence, then clear the review flag on both legs."""
    if tx.transfer_group_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transaction is already linked to a transfer group.",
        )
    if counterpart_id == tx.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A transaction cannot be its own transfer counterpart.",
        )
    counterpart = db.get(Transaction, counterpart_id)
    if counterpart is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggested counterpart not found.")
    if counterpart.transfer_group_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Suggested counterpart is already linked to a transfer group.",
        )
    # A transfer's two legs are always on different accounts with opposite-sign amounts — without
    # this check, a bad/misused counterpart id (e.g. a same-account, same-sign transaction) would
    # still pass every prior check and produce a nonsensical single-real-member "TransferGroup".
    if counterpart.account_id == tx.account_id or (counterpart.amount < 0) == (tx.amount < 0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Counterpart must be an opposite-sign transaction on a different account.",
        )

    group = TransferGroup(detection_tier=2, confidence=1.0)
    db.add(group)
    db.flush()
    for member in (tx, counterpart):
        member.transfer_group = group
        member.type = "Transfer"
        member.needs_review = False
        member.needs_review_reason = None


def _reject_transfer_match(db: Session, tx: Transaction) -> None:
    """
    "Not a transfer": if already auto-linked (Tier-2 High/Medium), unlink every leg of the group
    and revert `type` to what the amount sign implies, deleting the now-empty group; if only
    suggested (Tier-2 Low, never linked), just dismiss the flag on this row.
    """
    if tx.transfer_group_id is not None:
        group = tx.transfer_group
        for member in list(group.members):
            member.transfer_group_id = None
            member.type = "Income" if member.amount > 0 else "Expense"
            member.needs_review = False
            member.needs_review_reason = None
        db.delete(group)
    else:
        tx.needs_review = False
        tx.needs_review_reason = None


@app.get("/summary", response_model=SummaryOut)
def get_summary(
    db: Session = Depends(get_session),
    date_from: Optional[date_type] = Query(default=None),
    date_to: Optional[date_type] = Query(default=None),
    account_id: Optional[int] = Query(default=None),
) -> SummaryOut:
    """
    Income vs. expense over a period (J2, plus J7's Tax Refund filter as a category=Income query),
    excluding Transfer-typed and superseded rows.

    Buckets by `category`, not `type`: every income source (Salary, Interest, Tax Refund, ...) is
    seeded under the `Income` category (categorisation/taxonomy.py), while a genuine refund keeps
    the category of the purchase it's refunding — so grouping by category alone correctly nets a
    refund against its own category rather than counting it as income (FR-9b), even though the
    upload pipeline's `type` field is assigned from amount sign alone and would otherwise mislabel
    a refund credit as `Income`.
    """
    q = db.query(Transaction).filter(
        Transaction.type != "Transfer", Transaction.superseded_by_id.is_(None)
    )
    if date_from is not None:
        q = q.filter(Transaction.date >= date_from)
    if date_to is not None:
        q = q.filter(Transaction.date <= date_to)
    if account_id is not None:
        q = q.filter(Transaction.account_id == account_id)

    total_income = 0.0
    category_raw_totals: dict[str, float] = {}
    for tx in q.all():
        if tx.category == "Income":
            total_income += tx.amount
            continue
        label = tx.category or "Uncategorized"
        category_raw_totals[label] = category_raw_totals.get(label, 0.0) + tx.amount

    # Stored amounts are negative for spend, positive for a refund credit — negate so a category's
    # `amount` reads as "net spend" (positive), matching what a spend breakdown chart expects.
    by_category = sorted(
        (CategorySummary(category=c, amount=-raw) for c, raw in category_raw_totals.items()),
        key=lambda c: c.amount,
        reverse=True,
    )
    total_expense = sum(c.amount for c in by_category)

    return SummaryOut(
        date_from=date_from,
        date_to=date_to,
        total_income=total_income,
        total_expense=total_expense,
        net=total_income - total_expense,
        by_category=by_category,
    )
