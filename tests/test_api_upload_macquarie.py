from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.api as api_module
from backend.models import Account, AccountAlias, Base, CategorisationRule, Transaction
from categorisation.seed_rules import seed_rules_if_empty

CMA = "Macquarie Cash Management Account"
ACCELERATOR = "Macquarie Cash Management Accelerator Account"
HEADER = (
    "Transaction Date,Details,Account,Category,Subcategory,Tags,Notes,Debit,Credit,Balance,"
    "Original Description\n"
)
NAB_HEADER = "Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"

# JC pays $100,000 to Macquarie on 8 Oct; the Macquarie file shows the credit the same day.
NAB_JC = NAB_HEADER + "2025-10-08,-100000.00,JC,TRANSFER DEBIT,JC to Macquarie,500.00,Internal transfers,,\n"
MAC_CREDIT = HEADER + (
    f"2025-10-08,Mrs Anila Rohan Mayekar Jc To Macquarie,{CMA},Financial,Transfers,,,,100000,201000,"
    "MRS ANILA ROHAN MAYEKAR JC to Macquarie\n"
)
# Macquarie sends $5,100 on to the Accelerator, naming its account number; the Accelerator shows it.
MAC_OUT = HEADER + (
    f"2026-09-28,To Rohan Mayekar - Receipt number: 75517537 BSB: 182500 A/C: 000942290974,{CMA},"
    "Financial,Transfers,,,5100,,26992.85,To ROHAN MAYEKAR -\n"
)
ACCELERATOR_IN = HEADER + (
    f"2026-09-28,From Rohan Mayekar,{ACCELERATOR},Financial,Transfers,,,,5100,80997.56,From ROHAN MAYEKAR\n"
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test_finance.db'}", connect_args={"check_same_thread": False})
    session_local = sessionmaker(bind=engine)
    monkeypatch.setattr(api_module, "engine", engine)
    monkeypatch.setattr(api_module, "SessionLocal", session_local)
    Base.metadata.create_all(bind=engine)
    with session_local() as seed_session:
        seed_rules_if_empty(seed_session)
    with patch("categorisation.claude_fallback.anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        tool_block = MagicMock(type="tool_use", input={"category": "Miscellaneous", "subcategory": None, "confidence": 0.9})
        mock_client.messages.create.return_value = MagicMock(content=[tool_block])
        mock_anthropic.return_value = mock_client
        yield TestClient(api_module.app)


def _upload(client, content):
    return client.post(
        "/transactions/upload",
        files={"file": ("statement.csv", io.BytesIO(content.encode()), "text/csv")},
    )


def _register(account_name: str, *aliases: str) -> None:
    with api_module.SessionLocal() as db:
        account = Account(name=account_name)
        db.add(account)
        db.flush()
        for alias in aliases:
            db.add(AccountAlias(account_id=account.id, raw_identifier=alias))
        db.commit()


def _rows():
    with api_module.SessionLocal() as db:
        return db.query(Transaction).order_by(Transaction.id).all()


def test_a_macquarie_file_uploads_and_lands_on_its_registered_account(client):
    _register("Macquarie CMA", CMA)

    response = _upload(client, MAC_CREDIT)

    assert response.status_code == 201
    assert response.json()["count"] == 1
    (row,) = _rows()
    assert row.amount == 100000
    assert row.balance == 201000
    assert row.raw_transaction_type == "TRANSFER CREDIT"
    assert row.raw_bank_category is None
    with api_module.SessionLocal() as db:
        assert db.get(Account, row.account_id).name == "Macquarie CMA"


def test_an_unregistered_macquarie_account_is_created_and_flagged(client):
    _upload(client, MAC_CREDIT)

    (row,) = _rows()
    assert row.needs_review_reason == "unrecognised_account"


def test_the_nab_debit_to_macquarie_pairs_with_the_macquarie_credit(client):
    _register("Macquarie CMA", CMA)
    _upload(client, NAB_JC)
    _upload(client, MAC_CREDIT)

    jc, mac = _rows()
    assert jc.type == mac.type == "Transfer"
    assert jc.transfer_group_id is not None and jc.transfer_group_id == mac.transfer_group_id


def test_the_nab_debit_uploaded_after_the_macquarie_file_still_finds_its_credit(client):
    # The debit is typed Transfer by its text on upload, so it only gets a partner if upload detection
    # still runs on it; the opposite upload order is covered by the test above.
    _register("Macquarie CMA", CMA)
    _upload(client, MAC_CREDIT)
    _upload(client, NAB_JC)

    mac, jc = _rows()
    assert jc.transfer_group_id is not None and jc.transfer_group_id == mac.transfer_group_id


def test_macquarie_to_accelerator_pairs_through_the_account_number_in_the_details(client):
    # Tier 1: the debit's Details names the Accelerator's account number, registered as its alias.
    _register("Macquarie CMA", CMA)
    _register("Macquarie Accelerator", ACCELERATOR, "000942290974")
    _upload(client, MAC_OUT)
    _upload(client, ACCELERATOR_IN)

    out, into = _rows()
    assert out.transfer_group_id is not None and out.transfer_group_id == into.transfer_group_id


def test_uploading_mac_before_macacc_does_not_leave_the_debit_paired_with_a_salary_credit(client):
    # The real defect: MAC uploaded first, so its debit (whose Details name the Accelerator's account number)
    # found no MACACC credit and paired by amount and date with a same-day 'transfer salary' credit on a NAB
    # account. When the MACACC file arrives the number must win, and the salary must go back to being income.
    _register("Macquarie CMA", CMA)
    _register("Macquarie Accelerator", ACCELERATOR, "000942290974")
    salary = NAB_HEADER + "2026-09-28,5100.00,RC,TRANSFER CREDIT,ROHAN MAYEKARtransfer salary,9000.00,Income,,\n"
    _upload(client, salary)
    _upload(client, MAC_OUT)
    first_salary, first_out = _rows()
    assert first_salary.transfer_group_id == first_out.transfer_group_id is not None   # the wrong, interim pairing

    _upload(client, ACCELERATOR_IN)

    salary_row, out, into = _rows()
    assert out.transfer_group_id is not None and out.transfer_group_id == into.transfer_group_id
    assert salary_row.transfer_group_id is None and salary_row.type == "Income"


def test_interest_never_pairs_with_an_equal_and_opposite_row(client):
    _register("Macquarie CMA", CMA)
    interest = HEADER + f"2026-09-30,Interest,{CMA},Income,Interest,,,,61.60,100.00,MACQUARIE CMA INTEREST PAID\n"
    fee = NAB_HEADER + "2026-09-30,-61.60,AC,TRANSFER DEBIT,Some payment,10.00,Internal transfers,,\n"
    _upload(client, fee)
    _upload(client, interest)

    assert all(r.transfer_group_id is None for r in _rows())


def test_a_users_own_rule_beats_the_files_category_hint(client):
    _register("Macquarie CMA", CMA)
    with api_module.SessionLocal() as db:
        db.add(CategorisationRule(pattern="Macquarie Cma Interest Paid", match_type="exact", priority=1000,
                                  source="user_correction", is_active=True, category="Income", subcategory="Other"))
        db.commit()
    content = HEADER + (
        f"2026-09-30,Macquarie Cma Interest Paid,{CMA},Income,Interest,,,,61.6,100.00,MACQUARIE CMA INTEREST PAID\n"
    )

    _upload(client, content)

    (row,) = _rows()
    assert (row.category, row.subcategory) == ("Income", "Other")


def test_interest_and_dividends_are_categorised_from_the_files_own_labels(client):
    _register("Macquarie CMA", CMA)
    content = HEADER + (
        f"2026-09-30,Macquarie Cma Interest Paid,{CMA},Income,Interest,,,,61.6,100.00,MACQUARIE CMA INTEREST PAID\n"
        f"2026-05-01,Aqlt Dst 001348109967,{CMA},Income,Dividends & Distributions,,,,12.5,40.00,AQLT DST 001348109967\n"
        f"2026-05-02,Something Else,{CMA},Financial,Direct Debits,,,30,,10.00,SOMETHING ELSE\n"
    )
    _upload(client, content)

    interest, dividend, other = _rows()
    assert (interest.category, interest.subcategory, interest.needs_review) == ("Income", "Interest", False)
    assert (dividend.category, dividend.subcategory, dividend.needs_review) == (
        "Income", "Dividends & Distributions", False)
    # A direct debit carries no hint, so it goes through the normal fallback (the mocked LLM here) rather
    # than being given an income category.
    assert other.category == "Miscellaneous"
