from __future__ import annotations

from io import BytesIO
from typing import Dict

from fastapi.testclient import TestClient

from backend.api import app

from .common import reset_transactions_table


def test_e2e_upload_transactions_and_fetch_via_api() -> None:
    """
    Full-flow test: CSV upload -> ingestion -> categorisation -> DB -> /transactions and /summary.
    """
    reset_transactions_table()

    csv_content = (
        "Date,Description,Amount\n"
        "2026-01-05,UBER TRIP,-22.40\n"
        "2026-01-06,WOOLWORTHS 3345,-85.20\n"
        "2026-01-08,NETFLIX.COM,-15.99\n"
        "2026-01-10,SOME UNKNOWN SHOP,-5.00\n"
    )
    files = {
        "file": ("test.csv", BytesIO(csv_content.encode("utf-8")), "text/csv"),
    }

    client = TestClient(app)

    # Upload CSV and confirm basic response.
    upload_resp = client.post("/upload-transactions", files=files)
    assert upload_resp.status_code == 201
    upload_data = upload_resp.json()
    assert upload_data["message"] == "Transactions imported successfully."
    assert upload_data["count"] == 4

    # Fetch all transactions and verify they were persisted with merchants and categories.
    tx_resp = client.get("/transactions")
    assert tx_resp.status_code == 200
    transactions = tx_resp.json()
    assert isinstance(transactions, list)
    assert len(transactions) == 4

    merchants = {t["merchant"] for t in transactions}
    categories_by_merchant: Dict[str, str] = {
        t["merchant"]: t["category"] for t in transactions
    }

    # Known merchants should be correctly extracted and categorised.
    assert {"Uber", "Woolworths", "Netflix"}.issubset(merchants)

    assert categories_by_merchant["Uber"] == "Transport"
    assert categories_by_merchant["Woolworths"] == "Groceries"
    assert categories_by_merchant["Netflix"] == "Entertainment"

    # There should be exactly one additional merchant beyond the known ones,
    # and it should still receive some (fallback) category.
    assert len(merchants) == 4
    extra_merchants = merchants - {"Uber", "Woolworths", "Netflix"}
    assert len(extra_merchants) == 1
    extra = next(iter(extra_merchants))
    assert categories_by_merchant[extra] is not None

    # Verify /summary aggregates amounts by category.
    summary_resp = client.get("/summary")
    assert summary_resp.status_code == 200
    summary_items = summary_resp.json()
    assert isinstance(summary_items, list)
    assert summary_items

    by_category = {item["category"]: item["total_amount"] for item in summary_items}

    # Totals should reflect the raw negative amounts per category.
    assert by_category["Transport"] == -22.40
    assert by_category["Groceries"] == -85.20
    assert by_category["Entertainment"] == -15.99

