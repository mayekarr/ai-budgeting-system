from __future__ import annotations

from datetime import date

import pytest

from ingestion.nab_format import NabFormatError, parse_nab_format

SAMPLE_CSV = (
    "Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
    "2026-08-08,-38.66,Card ending 2957,PURCHASE AUTHORISATION,"
    "HILLS MEATS PTY LTDHILLS Forest Hill 036,-4131.90,Services,Hills Meats,\n"
    "2026-08-05,8050.20,Card ending 7128,CREDIT CARD PAYMENT,DIRECT DEBIT PAYMENT,-3781.44,"
    "Internal transfers,,2026-08-05\n"
)


def test_parses_real_shape_rows():
    rows = parse_nab_format(SAMPLE_CSV.encode(), filename="statement.csv")

    assert len(rows) == 2
    first = rows[0]
    assert first.date == date(2026, 8, 8)
    assert first.amount == -38.66
    assert first.account_identifier == "Card ending 2957"
    assert first.raw_transaction_type == "PURCHASE AUTHORISATION"
    assert first.raw_description == "HILLS MEATS PTY LTDHILLS Forest Hill 036"
    assert first.balance == -4131.90


def test_bank_provided_category_is_read_separately_not_as_the_category_field():
    # §4.1: bank-assigned Category is demonstrably unreliable as a *transfer/refund type* signal
    # (e.g. real invoices mislabeled "Transfers out") -- it's kept on its own field
    # (raw_bank_category), read separately from the actual classification output, never assigned
    # directly to ParsedRow.category (there is no such field). categorisation/bank_category.py
    # (2026-09-25) does use it as a categorisation *signal*, via a small curated mapping that
    # deliberately excludes exactly the transfer/refund-labelled values this finding is about.
    rows = parse_nab_format(SAMPLE_CSV.encode(), filename="statement.csv")
    assert not hasattr(rows[0], "category")


def test_merchant_name_is_captured():
    rows = parse_nab_format(SAMPLE_CSV.encode(), filename="statement.csv")
    assert rows[0].raw_merchant == "Hills Meats"
    assert rows[1].raw_merchant is None  # blank cell in the sample


def test_missing_required_column_raises_nab_format_error():
    bad_csv = "Date,Amount\n2026-08-08,-38.66\n"
    with pytest.raises(NabFormatError):
        parse_nab_format(bad_csv.encode(), filename="statement.csv")


def test_malformed_row_is_surfaced_not_silently_dropped():
    bad_csv = (
        "Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
        "not-a-date,-38.66,Card ending 2957,PURCHASE AUTHORISATION,Some Merchant,-100.00,,,\n"
    )
    with pytest.raises(NabFormatError):
        parse_nab_format(bad_csv.encode(), filename="statement.csv")


def test_blank_transaction_details_raises_instead_of_becoming_the_literal_string_nan():
    bad_csv = (
        "Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
        "2026-08-08,-38.66,Card ending 2957,PURCHASE AUTHORISATION,,-100.00,,,\n"
    )
    with pytest.raises(NabFormatError):
        parse_nab_format(bad_csv.encode(), filename="statement.csv")


def test_blank_account_number_raises_instead_of_becoming_the_literal_string_nan():
    bad_csv = (
        "Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
        "2026-08-08,-38.66,,PURCHASE AUTHORISATION,Some Merchant,-100.00,,,\n"
    )
    with pytest.raises(NabFormatError):
        parse_nab_format(bad_csv.encode(), filename="statement.csv")


def test_blank_transaction_type_raises_instead_of_becoming_the_literal_string_nan():
    bad_csv = (
        "Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
        "2026-08-08,-38.66,Card ending 2957,,Some Merchant,-100.00,,,\n"
    )
    with pytest.raises(NabFormatError):
        parse_nab_format(bad_csv.encode(), filename="statement.csv")


ZERO_ROW_CSV = (
    "Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
    "2026-08-08,-38.66,Card ending 2957,PURCHASE AUTHORISATION,HILLS MEATS,-100.00,,,\n"
    "2026-08-07,0.00,147912186,MISCELLANEOUS CREDIT,PLEASE NOTE FROM 06 AUG 2026 YOUR DEBIT INT RATE IS 15.41%,5.00,,,\n"
    "2026-08-06,-10.00,Card ending 2957,PURCHASE AUTHORISATION,CAFE,-61.34,,,\n"
)


def test_zero_dollar_rows_are_skipped_and_counted():
    from ingestion.nab_format import parse_nab_format_with_report

    result = parse_nab_format_with_report(ZERO_ROW_CSV.encode(), filename="statement.csv")

    assert [r.raw_description for r in result.rows] == ["HILLS MEATS", "CAFE"]
    assert result.zero_amount_skipped == 1


def test_parse_nab_format_also_omits_zero_dollar_rows():
    rows = parse_nab_format(ZERO_ROW_CSV.encode(), filename="statement.csv")

    assert all(r.amount != 0 for r in rows)
    assert len(rows) == 2


def test_file_without_zero_dollar_rows_reports_zero_skipped():
    from ingestion.nab_format import parse_nab_format_with_report

    assert parse_nab_format_with_report(SAMPLE_CSV.encode(), filename="s.csv").zero_amount_skipped == 0
