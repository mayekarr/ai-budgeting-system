from __future__ import annotations

import io
from datetime import date

import pandas as pd
import pytest

from ingestion.commbank_format import CommbankFormatError, parse_commbank_dataframe
from ingestion.nab_format import NabFormatError
from ingestion.statement_parser import parse_statement_with_report

# The real NBA file: no header row, no account column. Newest first.
SAMPLE_CSV = (
    "2026-09-30,5033.81,Salary STAFF DEPARTMENT 00497982,5080.54\n"
    "2026-09-30,-3000.00,Transfer To ROHAN MAYEKAR PayID Phone from CommBank App transfer sydney expenses,46.73\n"
    "2026-09-29,32.40,Direct Credit 401507 CBA DIV 001360617378,601.49\n"
    "2026-09-25,-100.00,Transfer To ARVAN MAYEKAR PayID Phone from CommBank App arvan petrol,569.09\n"
    "2026-09-22,500.00,Fast Transfer From MR ROHAN ASHOK MAYEKA to PayID Email CREDIT TO ACCOUNT,669.09\n"
    "2026-09-20,-46.00,MORE TELECOM AU,169.09\n"
    "2026-09-19,6.99,Refund Purchase FANTUAN DELIVERY,215.09\n"
    "2026-09-18,186.14,Direct Credit 401507 DGS REGO REBATE 22.06.26,208.10\n"
)


def _parse(csv: str = SAMPLE_CSV, account: str | None = "NBA"):
    return parse_statement_with_report(csv.encode(), filename="NBA.csv", account=account)


def test_every_row_is_read_because_the_first_line_is_data_not_a_header():
    result = _parse()

    assert len(result.rows) == 8
    assert result.rows[0].date == date(2026, 9, 30) and result.rows[0].amount == 5033.81


def test_columns_are_date_amount_description_balance_and_the_account_comes_from_the_caller():
    first = _parse().rows[0]

    assert (first.raw_description, first.balance, first.account_identifier) == (
        "Salary STAFF DEPARTMENT 00497982", 5080.54, "NBA")


@pytest.mark.parametrize("index, expected_type", [
    (0, "SALARY"),
    (1, "TRANSFER DEBIT"),
    (2, "DIVIDEND"),
    (3, "TRANSFER DEBIT"),
    (4, "TRANSFER CREDIT"),
    (5, "PURCHASE AUTHORISATION"),
    (6, "CREDIT CARD REFUND"),
    (7, ""),                      # an unlabelled credit: no bank type, which the matcher allows
])
def test_bank_type_is_derived_from_the_description(index, expected_type):
    assert _parse().rows[index].raw_transaction_type == expected_type


def test_salary_and_dividend_rows_carry_a_category_hint_and_others_do_not():
    rows = _parse().rows

    assert rows[0].category_hint == ("Income", "Salary")
    assert rows[2].category_hint == ("Income", "Dividends & Distributions")
    assert rows[1].category_hint is None and rows[5].category_hint is None


@pytest.mark.parametrize("line, expected_type", [
    ("2025-07-12,-120.00,Transfer to xx2801 CommBank app,500.00", "PURCHASE AUTHORISATION"),
    ("2025-06-21,-50.00,Transfer to xx2801 Branch 063109,500.00", "PURCHASE AUTHORISATION"),
    ("2025-07-13,2.30,Transfer from xx2801 CommBank app,500.00", "DEPOSIT"),
])
def test_money_moved_to_or_from_the_travel_account_is_an_expense_never_a_transfer_leg(line, expected_type):
    # xx2801 is the travel account (Rohan, 2026-11-03): its statements are not imported, so a payment into it is
    # spending and must not pair with an equal credit elsewhere.
    csv = "2026-09-30,5033.81,Salary STAFF DEPARTMENT 00497982,5080.54\n" + line + "\n"

    row = _parse(csv).rows[1]

    assert row.raw_transaction_type == expected_type
    assert row.category_hint == ("Travel & Holidays", "Other")


def test_a_transfer_to_another_account_number_is_still_a_transfer():
    csv = "2026-09-30,5033.81,Salary STAFF DEPARTMENT 00497982,5080.54\n2025-07-12,-120.00,Transfer to xx9999 CommBank app,500.00\n"

    row = _parse(csv).rows[1]

    assert row.raw_transaction_type == "TRANSFER DEBIT" and row.category_hint is None


def test_slash_dates_in_a_csv_are_read_day_first():
    # CommBank's own CSV writes dd/mm/yyyy; month-first would turn 5 Sep into 9 May without any error.
    csv = "30/09/2026,5033.81,Salary STAFF DEPARTMENT 00497982,5080.54\n05/09/2026,-46.00,MORE TELECOM AU,47.00\n"

    rows = _parse(csv).rows

    assert [r.date for r in rows] == [date(2026, 9, 30), date(2026, 9, 5)]


def test_the_result_names_the_institution_so_an_account_can_be_stamped_with_it():
    assert _parse().institution == "CommBank"


def test_there_is_no_bank_category_to_save():
    assert all(r.raw_bank_category is None for r in _parse().rows)


def test_a_headerless_file_needs_an_account_because_it_names_none():
    with pytest.raises(NabFormatError, match="account"):
        _parse(account=None)


def test_a_blank_account_is_refused_too():
    with pytest.raises(NabFormatError, match="account"):
        _parse(account="  ")


def test_an_account_given_for_a_file_that_has_its_own_is_ignored():
    nab = (
        "Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
        "2026-08-08,-38.66,Card ending 2957,PURCHASE AUTHORISATION,HILLS MEATS,-4131.90,Services,Hills Meats,\n"
    )

    result = parse_statement_with_report(nab.encode(), filename="AC.csv", account="NBA")

    assert result.rows[0].account_identifier == "Card ending 2957"


def test_an_xlsx_without_a_header_is_recognised_too():
    frame = pd.DataFrame([
        [pd.Timestamp("2026-09-30"), 5033.81, "Salary STAFF DEPARTMENT 00497982", 5080.54],
        [pd.Timestamp("2026-09-29"), -46.0, "MORE TELECOM AU", 169.09],
    ])
    buffer = io.BytesIO()
    frame.to_excel(buffer, header=False, index=False)

    result = parse_statement_with_report(buffer.getvalue(), filename="NBA.xlsx", account="NBA")

    assert [r.amount for r in result.rows] == [5033.81, -46.0]
    assert result.rows[1].date == date(2026, 9, 29)


def test_zero_amount_rows_are_skipped_and_counted():
    csv = SAMPLE_CSV + "2026-09-01,0.00,Notice,208.10\n"

    result = _parse(csv)

    assert len(result.rows) == 8 and result.zero_amount_skipped == 1


@pytest.mark.parametrize("line", [
    "not-a-date,10.00,Something,5.00",
    "2026-09-01,abc,Something,5.00",
    "2026-09-01,10.00,,5.00",
])
def test_a_malformed_row_is_surfaced_not_dropped(line):
    # A valid first line keeps the file recognisable as headerless; the bad row follows it.
    csv = "2026-09-30,5033.81,Salary STAFF DEPARTMENT 00497982,5080.54\n" + line + "\n"

    with pytest.raises(CommbankFormatError):
        _parse(csv)


def test_a_file_of_the_wrong_width_is_refused():
    with pytest.raises(NabFormatError):
        parse_commbank_dataframe(pd.DataFrame([[date(2026, 9, 1), 10.0, "x"]]), "NBA")


def test_commbank_errors_are_nab_format_errors_so_the_upload_route_handles_them():
    assert issubclass(CommbankFormatError, NabFormatError)
