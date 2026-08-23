from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.api as api_module
from backend.models import Account, AccountAlias, Base
from categorisation.seed_rules import seed_rules_if_empty

SAMPLE_CSV = (
    "Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
    "2026-08-08,-38.66,Card ending 2957,PURCHASE AUTHORISATION,"
    "HILLS MEATS PTY LTDHILLS Forest Hill 036,-4131.90,Services,Hills Meats,\n"
    "2026-08-07,-50.00,Card ending 2957,CREDIT CARD PURCHASE,"
    "MYKI PAYMENTS MELBOURNE,-3781.44,Public transport,Myki Payments,2026-08-07\n"
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test_finance.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(bind=engine)

    monkeypatch.setattr(api_module, "engine", engine)
    monkeypatch.setattr(api_module, "SessionLocal", TestSessionLocal)
    Base.metadata.create_all(bind=engine)
    # TestClient(app) without `with` doesn't run the lifespan startup event, so seed explicitly
    # rather than relying on it firing implicitly.
    with TestSessionLocal() as seed_session:
        seed_rules_if_empty(seed_session)

    with patch("categorisation.claude_fallback.anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        tool_block = MagicMock(type="tool_use", input={"category": "Miscellaneous", "subcategory": None, "confidence": 0.9})
        mock_client.messages.create.return_value = MagicMock(content=[tool_block])
        mock_anthropic.return_value = mock_client
        yield TestClient(api_module.app)


def _upload(client, content=SAMPLE_CSV):
    return client.post(
        "/transactions/upload",
        files={"file": ("statement.csv", io.BytesIO(content.encode()), "text/csv")},
    )


def test_upload_persists_and_categorises_transactions(client):
    response = _upload(client)

    assert response.status_code == 201
    body = response.json()
    assert body["count"] == 2

    listed = client.get("/transactions").json()
    assert len(listed) == 2
    myki = next(t for t in listed if "MYKI" in t["raw_description"])
    # A real seeded rule (from Source 1) must have matched — proves rule-matching actually ran,
    # not just that the mocked Claude fallback filled in something non-null.
    assert myki["category"] == "Transport"
    assert myki["subcategory"] == "Public Transport"


def test_reupload_same_statement_does_not_duplicate(client):
    _upload(client)
    response = _upload(client)

    assert response.status_code == 201
    assert response.json()["count"] == 0  # nothing new, both rows already existed

    listed = client.get("/transactions").json()
    assert len(listed) == 2


def test_get_transactions_filters_by_category(client):
    _upload(client)

    listed = client.get("/transactions", params={"category": "Transport"}).json()
    for t in listed:
        assert t["category"] == "Transport"


def _tool_block(category, confidence, subcategory=None):
    return MagicMock(type="tool_use", input={"category": category, "subcategory": subcategory, "confidence": confidence})


def test_needs_review_count_reflects_only_this_uploads_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "test_finance.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(bind=engine)
    monkeypatch.setattr(api_module, "engine", engine)
    monkeypatch.setattr(api_module, "SessionLocal", TestSessionLocal)
    Base.metadata.create_all(bind=engine)
    with TestSessionLocal() as seed_session:
        seed_rules_if_empty(seed_session)

    with patch("categorisation.claude_fallback.anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        # Upload 1: an unmatched merchant, low confidence -> flagged for review.
        mock_client.messages.create.return_value = MagicMock(content=[_tool_block("Miscellaneous", 0.3)])
        mock_anthropic.return_value = mock_client
        client = TestClient(api_module.app)

        csv1 = ("Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
                "2026-08-01,-12.34,Card ending 2957,CREDIT CARD PURCHASE,SOME UNKNOWN MERCHANT XYZ,-100.00,,,\n")
        r1 = _upload(client, csv1)
        assert r1.json()["needs_review_count"] == 1

        # Upload 2: a rule-matched merchant, high confidence -> nothing new needs review, but the
        # response must not still report upload 1's leftover flagged row.
        csv2 = ("Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
                "2026-08-02,-28.82,Card ending 2957,CREDIT CARD PURCHASE,WOOLWORTHS/MAIN ST,-71.18,,,\n")
        r2 = _upload(client, csv2)
        assert r2.json()["needs_review_count"] == 0


def test_ato_override_clears_a_stale_low_confidence_review_flag(tmp_path, monkeypatch):
    db_path = tmp_path / "test_finance.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(bind=engine)
    monkeypatch.setattr(api_module, "engine", engine)
    monkeypatch.setattr(api_module, "SessionLocal", TestSessionLocal)
    Base.metadata.create_all(bind=engine)
    with TestSessionLocal() as seed_session:
        seed_rules_if_empty(seed_session)
        # Pre-register the account so resolved.needs_review is False — isolates the thing this
        # test actually checks (the categorisation-confidence flag) from account resolution.
        account = Account(name="CC", institution="NAB", owner="Rohan", account_type="Credit Card")
        seed_session.add(account)
        seed_session.flush()
        seed_session.add(AccountAlias(account_id=account.id, raw_identifier="Card ending 2957"))
        seed_session.commit()

    with patch("categorisation.claude_fallback.anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        # Categorisation alone would be low-confidence (no rule matches "ATO..." text) — but the
        # ATO override replaces category/subcategory with a confident, deterministic value, and
        # the persisted row must not still carry the stale needs_review flag from before it did.
        mock_client.messages.create.return_value = MagicMock(content=[_tool_block("Miscellaneous", 0.3)])
        mock_anthropic.return_value = mock_client
        client = TestClient(api_module.app)

        csv = ("Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
               "2026-08-01,450.00,Card ending 2957,DIRECT CREDIT,ATO TAX REFUND NOTICE 2026,-100.00,,,\n")
        _upload(client, csv)

        listed = client.get("/transactions").json()
        row = listed[0]
        assert row["category"] == "Income"
        assert row["subcategory"] == "Tax Refund"
        assert row["needs_review"] is False


def test_ato_override_is_not_overwritten_by_a_coincidental_transfer_match(tmp_path, monkeypatch):
    # A tax refund's description happens to mention another account's alias, and that other
    # account has an unrelated transaction of the exact opposite amount within the matching
    # window — pure coincidence, not a real transfer. Transfer detection must not be allowed to
    # overwrite the deliberate, confident ATO override.
    db_path = tmp_path / "test_finance.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(bind=engine)
    monkeypatch.setattr(api_module, "engine", engine)
    monkeypatch.setattr(api_module, "SessionLocal", TestSessionLocal)
    Base.metadata.create_all(bind=engine)
    with TestSessionLocal() as seed_session:
        seed_rules_if_empty(seed_session)
        cc = Account(name="CC", institution="NAB", owner="Rohan", account_type="Credit Card")
        jc = Account(name="JC", institution="NAB", owner="Rohan", account_type="Everyday")
        seed_session.add_all([cc, jc])
        seed_session.flush()
        seed_session.add_all([
            AccountAlias(account_id=cc.id, raw_identifier="Card ending 2957"),
            AccountAlias(account_id=jc.id, raw_identifier="147912573"),
        ])
        seed_session.commit()

    with patch("categorisation.claude_fallback.anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(content=[_tool_block("Miscellaneous", 0.9)])
        mock_anthropic.return_value = mock_client
        client = TestClient(api_module.app)

        csv = (
            "Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
            "2026-08-01,450.00,Card ending 2957,DIRECT CREDIT,ATO TAX REFUND ACC 147912573,-100.00,,,\n"
            "2026-08-01,-450.00,147912573,TRANSFER DEBIT,UNRELATED COINCIDENTAL PAYMENT,-500.00,,,\n"
        )
        _upload(client, csv)

        listed = client.get("/transactions").json()
        ato_row = next(t for t in listed if "ATO" in t["raw_description"])
        assert ato_row["category"] == "Income"
        assert ato_row["subcategory"] == "Tax Refund"
        assert ato_row["type"] == "Income"
        assert ato_row["transfer_group_id"] is None


def test_persistence_failure_returns_controlled_500_not_unhandled_exception(client, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(api_module, "bulk_save_transactions", _boom)

    response = _upload(client)

    assert response.status_code == 500
