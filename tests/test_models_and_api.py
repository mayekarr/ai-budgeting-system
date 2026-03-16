from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from backend.api import app
from backend.database import SessionLocal, create_tables
from backend.models import Transaction


def test_transaction_model_has_recommended_fields() -> None:
    """
    Ensure the Transaction ORM model exposes all recommended columns.
    """
    column_names = {c.name for c in Transaction.__table__.columns}

    # Core fields
    assert "id" in column_names
    assert "date" in column_names
    assert "description" in column_names
    assert "merchant" in column_names
    assert "amount" in column_names
    assert "category" in column_names

    # Extended fields
    assert "subcategory" in column_names
    assert "currency" in column_names
    assert "account_id" in column_names
    assert "confidence_score" in column_names
    assert "created_at" in column_names


def test_transactions_endpoint_includes_extended_fields(tmp_path) -> None:
    """
    Ensure /transactions returns the extended schema fields for each transaction.
    """
    # Make sure tables exist
    create_tables()

    # Insert a simple transaction row
    session = SessionLocal()
    try:
        tx = Transaction(
            date=date(2026, 1, 5),
            description="TEST TRANSACTION",
            merchant="TestMerchant",
            amount=-10.0,
            category="TestCategory",
        )
        session.add(tx)
        session.commit()
        session.refresh(tx)
        tx_id = tx.id
    finally:
        session.close()

    client = TestClient(app)
    resp = client.get("/transactions")
    assert resp.status_code == 200

    data = resp.json()
    assert isinstance(data, list)
    assert any(item["id"] == tx_id for item in data)

    # Check shape of first item
    first = data[0]
    for key in (
        "id",
        "date",
        "description",
        "merchant",
        "amount",
        "category",
        "subcategory",
        "currency",
        "account_id",
        "confidence_score",
        "created_at",
    ):
        assert key in first

