from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.api as api_module
from backend.models import Account, AccountAlias, Base, Transaction
from categorisation.seed_rules import seed_rules_if_empty

NAB_HEADER = "Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
# The headerless NBA export: date, amount, description, balance. Newest first.
NBA = (
    "2026-09-30,5033.81,Salary STAFF DEPARTMENT 00497982,5080.54\n"
    "2026-09-25,-1000.00,Transfer To ROHAN MAYEKAR PayID Phone from CommBank App transfer salary,669.09\n"
)
# RC receives the forwarded $1,000.
RC = NAB_HEADER + "2026-09-25,1000.00,133500607,TRANSFER CREDIT,ROHAN MAYEKARtransfer salary,9000.00,Income,,\n"


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


def _upload(client, content, filename="statement.csv", **params):
    return client.post(
        "/transactions/upload",
        params=params,
        files={"file": (filename, io.BytesIO(content.encode()), "text/csv")},
    )


def _register_nba() -> None:
    with api_module.SessionLocal() as db:
        account = Account(name="NBA", institution="CommBank")
        db.add(account)
        db.flush()
        db.add(AccountAlias(account_id=account.id, raw_identifier="NBA"))
        db.commit()


def _rows():
    with api_module.SessionLocal() as db:
        return db.query(Transaction).order_by(Transaction.id).all()


def test_a_headerless_file_without_an_account_is_a_clear_400(client):
    response = _upload(client, NBA, filename="NBA.csv")

    assert response.status_code == 400
    assert "account" in response.json()["detail"]
    assert _rows() == []


def test_a_headerless_file_lands_on_the_named_account_with_every_row(client):
    _register_nba()

    response = _upload(client, NBA, filename="NBA.csv", account="NBA")

    assert response.status_code == 201 and response.json()["count"] == 2
    salary, forward = _rows()
    with api_module.SessionLocal() as db:
        assert db.get(Account, salary.account_id).name == "NBA"
    assert (salary.date.isoformat(), salary.amount, salary.balance) == ("2026-09-30", 5033.81, 5080.54)


def test_the_salary_credit_is_income_and_not_left_for_review(client):
    _register_nba()
    _upload(client, NBA, filename="NBA.csv", account="NBA")

    salary, _ = _rows()
    assert (salary.type, salary.category, salary.subcategory, salary.needs_review) == ("Income", "Income", "Salary", False)
    assert salary.raw_transaction_type == "SALARY"


def test_the_forward_to_rc_pairs_with_the_rc_credit(client):
    _register_nba()
    _upload(client, RC)
    _upload(client, NBA, filename="NBA.csv", account="NBA")

    rc, _salary, forward = _rows()
    assert rc.transfer_group_id is not None and rc.transfer_group_id == forward.transfer_group_id
    assert rc.type == forward.type == "Transfer"


def test_an_unknown_account_is_a_400_not_a_new_account(client):
    _register_nba()

    response = _upload(client, NBA, filename="NBA.csv", account="NBB")

    assert response.status_code == 400
    assert "NBB" in response.json()["detail"] and "NBA" in response.json()["detail"]   # names it and lists the known ones
    assert _rows() == []
    with api_module.SessionLocal() as db:
        assert db.query(Account).count() == 1


def test_the_account_is_matched_ignoring_case_and_lands_on_the_registered_one(client):
    _register_nba()

    response = _upload(client, NBA, filename="NBA.csv", account="nba")

    assert response.status_code == 201
    with api_module.SessionLocal() as db:
        assert db.query(Account).count() == 1
        assert {db.get(Account, r.account_id).name for r in _rows()} == {"NBA"}


def test_an_account_registered_without_an_institution_gets_it_from_the_file_format(client):
    # The rebuild guard recognises a format with no bank category by the account's institution.
    with api_module.SessionLocal() as db:
        account = Account(name="NBA")
        db.add(account)
        db.flush()
        db.add(AccountAlias(account_id=account.id, raw_identifier="NBA"))
        db.commit()

    _upload(client, NBA, filename="NBA.csv", account="NBA")

    with api_module.SessionLocal() as db:
        assert db.query(Account).filter_by(name="NBA").one().institution == "CommBank"


def test_an_existing_institution_is_never_overwritten(client):
    _register_nba()
    with api_module.SessionLocal() as db:
        db.query(Account).filter_by(name="NBA").one().institution = "Something Else"
        db.commit()

    _upload(client, NBA, filename="NBA.csv", account="NBA")

    with api_module.SessionLocal() as db:
        assert db.query(Account).filter_by(name="NBA").one().institution == "Something Else"


def test_the_account_parameter_is_ignored_for_a_file_that_names_its_own(client):
    response = _upload(client, RC, account="NBA")

    assert response.status_code == 201
    (row,) = _rows()
    with api_module.SessionLocal() as db:
        assert db.get(Account, row.account_id).name == "133500607"
