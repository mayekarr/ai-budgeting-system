from __future__ import annotations

from typing import List

import logging
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from categorisation.categoriser import categorise_merchant
from categorisation.merchant_parser import extract_merchant
from ingestion.csv_importer import CsvImportError, ImportedTransaction, load_transactions

from .database import bulk_save_transactions, create_tables, get_session
from .models import Transaction

logger = logging.getLogger(__name__)

app = FastAPI(title="AI Personal Budgeting and Expense Categorisation System")

# Allow local frontends (e.g., Streamlit) to call the API easily.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For local MVP; tighten in production.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TransactionOut(BaseModel):
    """Response schema for a transaction."""
    id: int
    date: str
    description: str
    merchant: str | None
    amount: float
    category: str | None
     subcategory: str | None = None
     currency: str | None = None
     account_id: str | None = None
     confidence_score: float | None = None
     created_at: str | None = None

    class Config:
        orm_mode = True


class SummaryItem(BaseModel):
    """Spending summary grouped by category."""
    category: str
    total_amount: float


@app.on_event("startup")
def on_startup() -> None:
    """Initialize database tables at startup."""
    logger.info("FastAPI startup: initialising database tables.")
    create_tables()


@app.post(
    "/upload-transactions",
    status_code=status.HTTP_201_CREATED,
    response_model=dict,
)
async def upload_transactions(
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
) -> dict:
    """
    Upload a CSV file containing bank transactions.

    The CSV is parsed, merchants and categories are inferred,
    and transactions are stored in the database.
    """
    logger.info("Received upload-transactions request: filename=%s", file.filename)

    if not file.filename.lower().endswith(".csv"):
        logger.warning(
            "Rejected upload-transactions: unsupported file type for filename=%s",
            file.filename,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only CSV files are supported.",
        )

    try:
        contents = await file.read()
        logger.debug("Read %d bytes from uploaded file.", len(contents))
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Unable to read uploaded file.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to read uploaded file: {exc}",
        ) from exc

    try:
        imported: List[ImportedTransaction] = load_transactions(contents)
    except CsvImportError as exc:
        logger.warning("CSV import error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if not imported:
        logger.info("CSV import completed: no valid transactions found.")
        return {"message": "No valid transactions found in CSV.", "count": 0}

    to_persist = []
    for tx in imported:
        merchant = extract_merchant(tx.description)
        category = categorise_merchant(merchant)
        to_persist.append(
            {
                "date": tx.date,
                "description": tx.description,
                "merchant": merchant,
                "amount": tx.amount,
                "category": category,
            }
        )

    try:
        bulk_save_transactions(db, to_persist)
        db.commit()
    except Exception as exc:  # pylint: disable=broad-except
        db.rollback()
        logger.exception("Failed to save imported transactions.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save transactions: {exc}",
        ) from exc

    logger.info("Successfully imported %d transactions.", len(to_persist))
    return {
        "message": "Transactions imported successfully.",
        "count": len(to_persist),
    }


@app.get("/transactions", response_model=List[TransactionOut])
def list_transactions(db: Session = Depends(get_session)) -> List[TransactionOut]:
    """
    Retrieve all stored transactions.

    Transactions are ordered by date (descending) and then by id.
    """
    records = (
        db.query(Transaction)
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .all()
    )
    logger.info("Fetched %d transactions from database.", len(records))
    return records


@app.get("/summary", response_model=List[SummaryItem])
def summary_by_category(db: Session = Depends(get_session)) -> List[SummaryItem]:
    """
    Return spending summary grouped by category.

    Amounts are summed as stored; typically they will be negative
    for expenses and positive for income. The frontend may take
    absolute values for visualisations.
    """
    rows = (
        db.query(
            Transaction.category.label("category"),
            func.sum(Transaction.amount).label("total_amount"),
        )
        .group_by(Transaction.category)
        .all()
    )

    # Normalize category names for null values
    result = [
        SummaryItem(
            category=row.category or "Uncategorized",
            total_amount=float(row.total_amount or 0.0),
        )
        for row in rows
    ]
    logger.info("Computed summary for %d categories.", len(result))
    return result

