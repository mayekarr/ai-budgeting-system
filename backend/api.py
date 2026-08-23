from __future__ import annotations

from datetime import date as date_type
from typing import Generator, List, Optional

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from categorisation.claude_fallback import categorise_with_fallback
from categorisation.rules import match_rule
from categorisation.seed_rules import seed_rules_if_empty
from ingestion.account_resolution import resolve_account
from ingestion.nab_format import NabFormatError, parse_nab_format
from transfers.detection import process_transfer_detection
from transfers.refunds import detect_refund

from .database import SessionLocal, bulk_save_transactions, create_tables, engine  # noqa: F401  (engine kept for test monkeypatching)
from .models import Transaction

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
    confidence_score: float | None


class UploadResult(BaseModel):
    message: str
    count: int
    needs_review_count: int


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
                "needs_review": cat_needs_review or refund_decision.needs_review or resolved.needs_review,
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
) -> List[TransactionOut]:
    """Filterable transaction list (FR-13/FR-14; needs_review backs FR-10's review queue)."""
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

    records = q.order_by(Transaction.date.desc(), Transaction.id.desc()).all()
    logger.info("Fetched %d transactions.", len(records))
    return records
