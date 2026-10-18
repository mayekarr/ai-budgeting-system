from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.api as api_module
from backend.models import Account, AccountAlias, Asset, AssetAlias, Base
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


def test_upload_succeeds_without_configured_llm_credentials(tmp_path, monkeypatch):
    # No ANTHROPIC_API_KEY and no mocked client -- the real state before a key is ever set up (or
    # if it's deliberately never purchased). An unmatched-merchant row must be flagged for review,
    # not crash the whole upload the way an unhandled SDK auth error previously did.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db_path = tmp_path / "test_finance.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(bind=engine)
    monkeypatch.setattr(api_module, "engine", engine)
    monkeypatch.setattr(api_module, "SessionLocal", TestSessionLocal)
    Base.metadata.create_all(bind=engine)
    with TestSessionLocal() as seed_session:
        seed_rules_if_empty(seed_session)
        # Pre-register the account so resolved.needs_review is False -- isolates the thing this
        # test actually checks (the LLM-unavailable categorisation flag) from account resolution.
        account = Account(name="CC", institution="NAB", owner="Rohan", account_type="Credit Card")
        seed_session.add(account)
        seed_session.flush()
        seed_session.add(AccountAlias(account_id=account.id, raw_identifier="Card ending 2957"))
        seed_session.commit()

    no_key_client = TestClient(api_module.app)
    csv = ("Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
           "2026-08-01,-12.34,Card ending 2957,CREDIT CARD PURCHASE,SOME UNKNOWN MERCHANT XYZ,-100.00,,,\n")
    response = _upload(no_key_client, csv)

    assert response.status_code == 201
    assert response.json()["needs_review_count"] == 1

    listed = no_key_client.get("/transactions").json()
    row = listed[0]
    assert row["category"] == "Miscellaneous"
    assert row["needs_review"] is True
    # Distinct from a genuine low-confidence model judgement -- every future upload hits the same
    # wall while no key is configured, which is worth being able to tell apart in the queue.
    assert row["needs_review_reason"] == "llm_unavailable"


def test_upload_derives_category_from_bank_category_when_no_rule_matches(tmp_path, monkeypatch):
    # Real, quantified gap found live by Rohan: 409/422 real rows across CC/RC/AC/JC carry a
    # non-blank bank Category, and it was being parsed then discarded -- Rohan's explicit
    # instruction was to use it instead of hand-writing more one-off text rules. No
    # ANTHROPIC_API_KEY / mocked client here: this must resolve via the bank-category layer alone,
    # never reaching the (permanently unavailable) LLM fallback.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db_path = tmp_path / "test_finance.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(bind=engine)
    monkeypatch.setattr(api_module, "engine", engine)
    monkeypatch.setattr(api_module, "SessionLocal", TestSessionLocal)
    Base.metadata.create_all(bind=engine)
    with TestSessionLocal() as seed_session:
        seed_rules_if_empty(seed_session)
        account = Account(name="CC", institution="NAB", owner="Rohan", account_type="Credit Card")
        seed_session.add(account)
        seed_session.flush()
        seed_session.add(AccountAlias(account_id=account.id, raw_identifier="Card ending 2957"))
        seed_session.commit()

    no_key_client = TestClient(api_module.app)
    csv = (
        "Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
        "2026-08-01,-62.00,Card ending 2957,PURCHASE AUTHORISATION,SOME BRAND NEW GYM STUDIO XYZ,-100.00,"
        "Gym & fitness,Some Brand New Gym Studio,\n"
    )
    response = _upload(no_key_client, csv)

    assert response.status_code == 201
    assert response.json()["needs_review_count"] == 0  # resolved, not flagged

    row = no_key_client.get("/transactions").json()[0]
    assert row["category"] == "Health & Medical"
    assert row["subcategory"] == "Gym & Fitness"
    assert row["needs_review"] is False
    # Merchant Name is captured too (a separate, real gap -- it was parsed then discarded).
    assert row["merchant"] == "Some Brand New Gym Studio"


def test_upload_categorises_a_real_salary_credit_as_income_without_llm(tmp_path, monkeypatch):
    # The actual defect Rohan reported live: GET /summary's total_income showed $0 despite real
    # salary rows in the uploaded data, because no seed rule recognised salary/dividend text and
    # the LLM fallback is permanently unavailable (docs/product-requirements.md §4.3.1) -- so every
    # real income row silently landed in Miscellaneous. No ANTHROPIC_API_KEY / mocked client here,
    # matching that real environment: this must work off rule-matching alone.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db_path = tmp_path / "test_finance.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(bind=engine)
    monkeypatch.setattr(api_module, "engine", engine)
    monkeypatch.setattr(api_module, "SessionLocal", TestSessionLocal)
    Base.metadata.create_all(bind=engine)
    with TestSessionLocal() as seed_session:
        seed_rules_if_empty(seed_session)
        account = Account(name="JC", institution="NAB", owner="Rohan", account_type="Everyday")
        seed_session.add(account)
        seed_session.flush()
        seed_session.add(AccountAlias(account_id=account.id, raw_identifier="147912573"))
        seed_session.commit()

    no_key_client = TestClient(api_module.app)
    csv = ("Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
           "2026-08-01,5317.55,147912573,DIRECT CREDIT,SALARY/WAGES ANILA MAYEKAR,-100.00,,,\n")
    response = _upload(no_key_client, csv)

    assert response.status_code == 201
    assert response.json()["needs_review_count"] == 0  # confident rule match, no review needed

    row = no_key_client.get("/transactions").json()[0]
    assert row["category"] == "Income"
    assert row["subcategory"] == "Salary"
    assert row["needs_review"] is False

    summary = no_key_client.get("/summary").json()
    assert summary["total_income"] == 5317.55


def test_upload_tags_real_jc_rows_to_assets_without_changing_categories(tmp_path, monkeypatch):
    # J6: the real JC account is shared (card autopay, donations) but its loan lines name their own
    # loan accounts, and the rent credit names the property -- each lands on the right asset, and
    # the unrelated rows stay untagged.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db_path = tmp_path / "test_finance.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(bind=engine)
    monkeypatch.setattr(api_module, "engine", engine)
    monkeypatch.setattr(api_module, "SessionLocal", TestSessionLocal)
    Base.metadata.create_all(bind=engine)
    with TestSessionLocal() as seed_session:
        seed_rules_if_empty(seed_session)
        jericho = Asset(name="Jericho Ct", type="Real Estate")
        shares = Asset(name="Share Portfolio", type="Shares")
        seed_session.add_all([jericho, shares])
        seed_session.flush()
        seed_session.add(AssetAlias(asset_id=jericho.id, pattern="6 JERICHO CT"))
        jc = Account(name="JC", institution="NAB", owner="Rohan", account_type="Everyday")
        seed_session.add(jc)
        seed_session.flush()
        seed_session.add(AccountAlias(account_id=jc.id, raw_identifier="147912573"))
        for number, asset in [("34-188-5257", jericho), ("34-189-2465", shares)]:
            loan = Account(name=f"{asset.name} loan", account_type="Loan", asset_id=asset.id)
            seed_session.add(loan)
            seed_session.flush()
            seed_session.add(AccountAlias(account_id=loan.id, raw_identifier=number))
        seed_session.commit()
        jericho_id, shares_id = jericho.id, shares.id

    no_key_client = TestClient(api_module.app)
    csv = ("Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
           "2026-07-31,-4877.79,147912573,INTEREST,INTEREST CHARGED FROM A/C 34-188-5257,-100.00,,,\n"
           "2026-07-31,-3847.91,147912573,INTEREST,INTEREST CHARGED FROM A/C 34-189-2465,-200.00,,,\n"
           "2026-08-05,2704.86,147912573,DIRECT CREDIT,6 Jericho Ct Berwi The Apostoli Gro Anila Mayekar &,-300.00,,,\n"
           "2026-08-10,-50.00,147912573,DIRECT DEBIT,P0006175750 OXFAM AUSTRALIA Anila Mayekar,-400.00,Donations,,\n")
    assert _upload(no_key_client, csv).status_code == 201

    rows = {r["raw_description"]: r for r in no_key_client.get("/transactions").json()}
    assert rows["INTEREST CHARGED FROM A/C 34-188-5257"]["asset_id"] == jericho_id
    assert rows["INTEREST CHARGED FROM A/C 34-189-2465"]["asset_id"] == shares_id
    rent = rows["6 Jericho Ct Berwi The Apostoli Gro Anila Mayekar &"]
    assert rent["asset_id"] == jericho_id
    assert (rent["category"], rent["subcategory"]) == ("Income", "Rental Income")
    assert rows["INTEREST CHARGED FROM A/C 34-188-5257"]["category"] == "Loans & Finance"
    assert rows["P0006175750 OXFAM AUSTRALIA Anila Mayekar"]["asset_id"] is None


def test_persistence_failure_returns_controlled_500_not_unhandled_exception(client, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(api_module, "bulk_save_transactions", _boom)

    response = _upload(client)

    assert response.status_code == 500


def _seam_repeat_csv(unique_rows: int, seam: int, block: int) -> str:
    """Newest-first export where the `block` rows before `seam` are re-listed right after it."""
    from datetime import date, timedelta

    def line(i: int) -> str:
        d = date(2026, 8, 20) - timedelta(days=i // 2)
        return f"{d.isoformat()},-{10 + i}.00,Card ending 2957,PURCHASE,SHOP {i} MELBOURNE,-100.00,,,"

    idx = list(range(unique_rows))
    idx = idx[:seam] + idx[seam - block : seam] + idx[seam:]
    header = "Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On"
    return header + "\n" + "\n".join(line(i) for i in idx) + "\n"


def test_upload_reports_dropped_seam_repeats(client):
    response = _upload(client, _seam_repeat_csv(unique_rows=60, seam=30, block=15))

    assert response.status_code == 201
    body = response.json()
    assert body["count"] == 60
    assert body["seam_repeats_dropped"] == 15
    assert "15" in body["message"]


def test_upload_without_seam_repeats_reports_zero_dropped(client):
    response = _upload(client)

    assert response.json()["seam_repeats_dropped"] == 0


def test_upload_types_loan_drawdowns_and_paydowns_as_transfer_but_not_instalments(client):
    csv = (
        "Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
        "2025-09-08,900000.00,147912573,MISCELLANEOUS CREDIT,LOAN PROCEEDS FROM A/C 34-188-5257,950000.00,,,\n"
        "2025-09-02,-582076.00,147912573,INTERNET TRANSFER,ONLINE N8131366871 JC to Barkly HL MAYEKAR A,50000.00,,,\n"
        "2025-09-01,-6489.89,147912573,LOAN REPAYMENT,LOAN REPAYMENT TO A/C 703206283 MAYEKAR A,632076.00,,,\n"
    )

    response = _upload(client, csv)

    assert response.status_code == 201
    with api_module.SessionLocal() as session:
        from backend.models import Transaction

        by_desc = {t.raw_description: t for t in session.query(Transaction)}
    drawdown = by_desc["LOAN PROCEEDS FROM A/C 34-188-5257"]
    assert drawdown.type == "Transfer"
    # Its category no longer matters, so no category flag is left. The only flag it can carry is
    # the new account's own unrecognised_account (first row on an unseen account).
    assert drawdown.needs_review_reason in (None, "unrecognised_account")
    paydown = by_desc["ONLINE N8131366871 JC to Barkly HL MAYEKAR A"]
    assert paydown.type == "Transfer"
    assert paydown.needs_review is False
    assert by_desc["LOAN REPAYMENT TO A/C 703206283 MAYEKAR A"].type == "Expense"
    assert client.get("/summary").json()["total_income"] == 0  # the $900,000 no longer counts as income


def test_loan_movement_is_never_left_flagged_as_a_refund(client, monkeypatch):
    # A Transfer cannot be a refund, even if the refund rules also fired on the same credit.
    from transfers.refunds import RefundDecision

    monkeypatch.setattr(
        api_module, "detect_refund",
        lambda *a, **k: RefundDecision(is_refund=True, route_to_income=False, needs_review=False),
    )
    csv = (
        "Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
        "2025-09-08,900000.00,147912573,MISCELLANEOUS CREDIT,LOAN PROCEEDS FROM A/C 34-188-5257,950000.00,,,\n"
    )

    assert _upload(client, csv).status_code == 201
    with api_module.SessionLocal() as session:
        from backend.models import Transaction

        tx = session.query(Transaction).one()
    assert tx.type == "Transfer"
    assert tx.is_refund is False


def test_loan_movement_does_not_keep_a_refund_ambiguity_flag(client, monkeypatch):
    # The flag is moot once the row is a Transfer; the backfill clears it, so upload must too.
    from transfers.refunds import RefundDecision

    monkeypatch.setattr(
        api_module, "detect_refund",
        lambda *a, **k: RefundDecision(is_refund=False, route_to_income=False, needs_review=True),
    )
    csv = (
        "Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
        "2025-09-08,50.00,147912573,MISCELLANEOUS CREDIT,SOMETHING ELSE,50.00,,,\n"
        "2025-09-09,900000.00,147912573,MISCELLANEOUS CREDIT,LOAN PROCEEDS FROM A/C 34-188-5257,950000.00,,,\n"
    )

    assert _upload(client, csv).status_code == 201
    with api_module.SessionLocal() as session:
        from backend.models import Transaction

        loan = session.query(Transaction).filter_by(raw_description="LOAN PROCEEDS FROM A/C 34-188-5257").one()
    assert loan.type == "Transfer"
    assert loan.needs_review_reason != "refund_ambiguity"


def test_upload_skips_zero_dollar_notice_rows_and_reports_them(client):
    csv = SAMPLE_CSV + (
        "2026-08-06,0.00,Card ending 2957,MISCELLANEOUS CREDIT,"
        "PLEASE NOTE FROM 05 AUG 2026 YOUR DEBIT INT RATE IS 15.41%,-3781.44,,,\n"
    )

    response = _upload(client, csv)

    assert response.status_code == 201
    body = response.json()
    assert body["count"] == 2
    assert body["zero_amount_skipped"] == 1
    assert "1" in body["message"]
    assert all(t["amount"] != 0 for t in client.get("/transactions").json())
