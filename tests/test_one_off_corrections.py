from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models import Account, Base, CategorisationRule, Transaction, TransferGroup
from categorisation.one_off_corrections import apply_corrections, load_corrections
from categorisation.taxonomy import is_valid_category


def test_taxonomy_has_the_property_and_investment_sale_subcategories():
    assert is_valid_category("Income", "Property Sale Proceeds")
    assert is_valid_category("Income", "Investment Sale Proceeds")
    assert is_valid_category("Investment", "Property Purchase")
    assert is_valid_category("Housing", "Property Purchase") is False


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        account = Account(name="JC")
        s.add(account)
        s.commit()
        s.info["account_id"] = account.id
        yield s


def _tx(session, day, amount, description, **kw):
    tx = Transaction(
        account_id=session.info["account_id"],
        date=day,
        amount=amount,
        raw_description=description,
        type=kw.pop("type", "Expense"),
        category=kw.pop("category", "Miscellaneous"),
        needs_review=kw.pop("needs_review", True),
        needs_review_reason=kw.pop("needs_review_reason", "llm_unavailable"),
        **kw,
    )
    session.add(tx)
    session.commit()
    return tx


def _entry(**kw):
    base = {"date": "2022-05-24", "amount": -209404.48, "description": "SETTLEMENT SHORTFALL",
            "type": "Expense", "category": "Investment", "subcategory": "Property Purchase"}
    base.update(kw)
    return base


def test_applies_category_and_clears_the_review_flag(session):
    tx = _tx(session, date(2022, 5, 24), -209404.48, "SETTLEMENT SHORTFALL")
    result = apply_corrections(session, [_entry()])
    session.refresh(tx)
    assert result["changed"] == 1
    assert (tx.type, tx.category, tx.subcategory) == ("Expense", "Investment", "Property Purchase")
    assert tx.needs_review is False and tx.needs_review_reason is None
    assert tx.confidence_score == 1.0


def test_rerun_changes_nothing(session):
    _tx(session, date(2022, 5, 24), -209404.48, "SETTLEMENT SHORTFALL")
    apply_corrections(session, [_entry()])
    again = apply_corrections(session, [_entry()])
    assert again["changed"] == 0
    assert again["already_applied"] == 1


def test_transfer_entry_nulls_category_and_refund_flag(session):
    tx = _tx(session, date(2023, 3, 20), -98149.28, "ONLINE N0344223448 JC to 99K MAYEKAR A")
    apply_corrections(session, [{"date": "2023-03-20", "amount": -98149.28,
                                 "description": "ONLINE N0344223448 JC to 99K MAYEKAR A", "type": "Transfer"}])
    session.refresh(tx)
    assert tx.type == "Transfer" and tx.category is None and tx.subcategory is None
    assert tx.is_refund is False and tx.needs_review is False


def test_refund_flag_can_be_set(session):
    tx = _tx(session, date(2025, 12, 1), 5000.0, "Waverley BMW", type="Income")
    apply_corrections(session, [{"date": "2025-12-01", "amount": 5000.0, "description": "Waverley BMW",
                                 "type": "Expense", "category": "Car", "subcategory": "Other", "is_refund": True}])
    session.refresh(tx)
    assert (tx.type, tx.category, tx.is_refund) == ("Expense", "Car", True)


def test_description_match_ignores_case_and_surrounding_whitespace(session):
    tx = _tx(session, date(2022, 5, 24), -209404.48, "SETTLEMENT SHORTFALL")
    apply_corrections(session, [_entry(description="  settlement shortfall ")])
    session.refresh(tx)
    assert tx.subcategory == "Property Purchase"


def test_no_matching_row_is_reported_not_raised(session):
    result = apply_corrections(session, [_entry()])
    assert result["changed"] == 0
    assert len(result["not_found"]) == 1


def test_ambiguous_match_is_skipped_unless_count_expected(session):
    a = _tx(session, date(2024, 11, 6), 1000.0, "SAME TEXT")
    b = _tx(session, date(2024, 11, 6), 1000.0, "SAME TEXT")
    entry = {"date": "2024-11-06", "amount": 1000.0, "description": "SAME TEXT",
             "type": "Income", "category": "Income", "subcategory": "Property Sale Proceeds"}
    result = apply_corrections(session, [entry])
    assert result["changed"] == 0 and len(result["ambiguous"]) == 1
    result = apply_corrections(session, [{**entry, "expect": 2}])
    session.refresh(a)
    session.refresh(b)
    assert result["changed"] == 2
    assert a.subcategory == b.subcategory == "Property Sale Proceeds"


def test_invalid_category_pair_is_rejected_and_row_untouched(session):
    tx = _tx(session, date(2022, 5, 24), -209404.48, "SETTLEMENT SHORTFALL")
    result = apply_corrections(session, [_entry(category="Groceries", subcategory="Flights")])
    session.refresh(tx)
    assert len(result["invalid"]) == 1 and result["changed"] == 0
    assert tx.category == "Miscellaneous"


def test_row_in_a_transfer_group_is_not_retyped_away_from_transfer(session):
    group = TransferGroup(detection_tier=1)
    session.add(group)
    session.commit()
    tx = _tx(session, date(2024, 1, 8), -6500.0, "for MLC", type="Transfer", transfer_group_id=group.id)
    result = apply_corrections(session, [_entry(date="2024-01-08", amount=-6500.0, description="for MLC")])
    session.refresh(tx)
    assert len(result["skipped_grouped"]) == 1
    assert tx.type == "Transfer"


def test_does_not_create_categorisation_rules(session):
    _tx(session, date(2022, 5, 24), -209404.48, "SETTLEMENT SHORTFALL")
    apply_corrections(session, [_entry()])
    assert session.query(CategorisationRule).count() == 0


def test_unrelated_review_reason_is_kept(session):
    tx = _tx(session, date(2022, 5, 24), -209404.48, "SETTLEMENT SHORTFALL", needs_review_reason="unrecognised_account")
    apply_corrections(session, [_entry()])
    session.refresh(tx)
    assert tx.needs_review is True and tx.needs_review_reason == "unrecognised_account"


def test_load_corrections_reads_json_list(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"corrections": [_entry()]}), encoding="utf-8")
    assert load_corrections(path) == [_entry()]


def test_commit_false_leaves_the_change_uncommitted(session):
    tx = _tx(session, date(2022, 5, 24), -209404.48, "SETTLEMENT SHORTFALL")
    result = apply_corrections(session, [_entry()], commit=False)
    assert result["changed"] == 1
    session.rollback()
    session.refresh(tx)
    assert tx.category == "Miscellaneous"


def test_multi_row_entry_with_a_grouped_row_is_skipped_whole(session):
    group = TransferGroup(detection_tier=1)
    session.add(group)
    session.commit()
    a = _tx(session, date(2024, 11, 6), 1000.0, "SAME TEXT")
    b = _tx(session, date(2024, 11, 6), 1000.0, "SAME TEXT", type="Transfer", transfer_group_id=group.id)
    entry = {"date": "2024-11-06", "amount": 1000.0, "description": "SAME TEXT", "expect": 2,
             "type": "Income", "category": "Income", "subcategory": "Other"}
    result = apply_corrections(session, [entry])
    session.refresh(a)
    session.refresh(b)
    assert result["changed"] == 0 and len(result["skipped_grouped"]) == 1
    assert a.category == "Miscellaneous" and b.type == "Transfer"


@pytest.mark.parametrize("bad", [
    {"date": "2022-05-24", "amount": -1.0, "description": "X", "type": "Expense"},  # no category
    {"date": "not-a-date", "amount": -1.0, "description": "X", "type": "Transfer"},
    {"date": "2022-05-24", "amount": -1.0, "description": "X", "type": "Income ", "category": "Income"},
    {"amount": -1.0, "description": "X", "type": "Transfer"},  # no date
])
def test_malformed_entries_are_reported_invalid_and_do_not_abort_the_run(session, bad):
    tx = _tx(session, date(2022, 5, 24), -209404.48, "SETTLEMENT SHORTFALL")
    result = apply_corrections(session, [bad, _entry()])
    session.refresh(tx)
    assert len(result["invalid"]) == 1
    assert tx.subcategory == "Property Purchase"


def test_already_correct_row_still_has_its_stale_review_flag_cleared(session):
    tx = _tx(session, date(2022, 5, 24), -209404.48, "SETTLEMENT SHORTFALL",
             category="Investment", **{"subcategory": "Property Purchase"})
    result = apply_corrections(session, [_entry()])
    session.refresh(tx)
    assert result["changed"] == 1
    assert tx.needs_review is False


def test_is_refund_is_left_alone_when_the_entry_does_not_mention_it(session):
    tx = _tx(session, date(2025, 9, 1), 900.0, "ATO REFUND", type="Income", is_refund=True)
    apply_corrections(session, [{"date": "2025-09-01", "amount": 900.0, "description": "ATO REFUND",
                                 "type": "Income", "category": "Income", "subcategory": "Tax Refund"}])
    session.refresh(tx)
    assert tx.is_refund is True and tx.subcategory == "Tax Refund"


@pytest.mark.parametrize("bad_expect", ["2", 2.0, 0, True, -1])
def test_non_integer_or_non_positive_expect_is_invalid_not_ambiguous(session, bad_expect):
    _tx(session, date(2022, 5, 24), -209404.48, "SETTLEMENT SHORTFALL")
    result = apply_corrections(session, [_entry(expect=bad_expect)])
    assert len(result["invalid"]) == 1 and result["ambiguous"] == []


@pytest.mark.parametrize("entry", [
    _entry(type="Expense", category="Income", subcategory="Property Sale Proceeds"),
    _entry(type="Income", category="Investment", subcategory="Property Purchase"),
])
def test_type_must_agree_with_category(session, entry):
    tx = _tx(session, date(2022, 5, 24), -209404.48, "SETTLEMENT SHORTFALL")
    result = apply_corrections(session, [entry])
    session.refresh(tx)
    assert len(result["invalid"]) == 1 and tx.category == "Miscellaneous"


@pytest.mark.parametrize("content", ["{not json", '{"correction": []}', '{"corrections": {"a": 1}}', "[1, 2]"])
def test_load_corrections_raises_a_clear_error_for_a_bad_file(tmp_path, content):
    path = tmp_path / "c.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="corrections"):
        load_corrections(path)


def test_script_reports_malformed_entries_without_crashing(tmp_path, monkeypatch, capsys):
    from scripts import apply_corrections as script
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"corrections": ["just a string", {"type": "Transfer"}]}), encoding="utf-8")
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    from contextlib import contextmanager

    @contextmanager
    def scope():
        with Session(engine) as s:
            yield s
            s.commit()

    monkeypatch.setattr(script, "session_scope", scope)
    monkeypatch.setattr(script, "create_tables", lambda: None)
    assert script.main(["x", str(path)]) == 1
    out = capsys.readouterr().out
    assert "invalid" in out and "just a string" in out
