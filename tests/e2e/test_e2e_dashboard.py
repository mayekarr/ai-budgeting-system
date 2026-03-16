from __future__ import annotations

from datetime import date
from io import BytesIO

from fastapi.testclient import TestClient

from backend.api import app
from backend.database import SessionLocal
from backend.models import Transaction
from frontend.dashboard import load_transactions_df

from .common import reset_transactions_table


def test_e2e_dashboard_reads_transactions_from_db() -> None:
    """
    Ensure the Streamlit dashboard's data loader sees data written to the DB.
    """
    reset_transactions_table()

    # Seed a single transaction directly via the ORM to avoid re-testing the upload endpoint here.
    session = SessionLocal()
    try:
        tx = Transaction(
            date=date(2026, 1, 12),
            description="AMAZON PURCHASE",
            merchant="Amazon",
            amount=-42.5,
            category="Shopping",
        )
        session.add(tx)
        session.commit()
    finally:
        session.close()

    df = load_transactions_df()
    assert not df.empty
    assert len(df) >= 1

    # Check that key columns expected by the dashboard are present.
    for col in ("id", "date", "description", "merchant", "amount", "category"):
        assert col in df.columns

    # The seeded transaction should be visible in the DataFrame.
    assert any(
        (row["description"] == "AMAZON PURCHASE" and row["amount"] == -42.5)
        for _, row in df.iterrows()
    )


def test_e2e_upload_then_dashboard_sees_data() -> None:
    """
    Smoke test that stitches the upload endpoint and dashboard data loader:
    CSV upload -> DB -> dashboard DataFrame.
    """
    reset_transactions_table()

    csv_content = (
        "Date,Description,Amount\n"
        "2026-02-01,UBER TRIP,-12.34\n"
    )
    files = {
        "file": ("smoke.csv", BytesIO(csv_content.encode("utf-8")), "text/csv"),
    }

    client = TestClient(app)
    upload_resp = client.post("/upload-transactions", files=files)
    assert upload_resp.status_code == 201

    df = load_transactions_df()
    assert not df.empty

    # The uploaded transaction should now be visible to the dashboard layer.
    assert any(
        (row["description"] == "UBER TRIP" and row["amount"] == -12.34)
        for _, row in df.iterrows()
    )

