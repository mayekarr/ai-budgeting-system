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


def test_bank_provided_category_is_not_trusted_as_the_category():
    # §4.1: bank-assigned Category is read but must never be used as the classification output —
    # it's demonstrably unreliable (e.g. real invoices mislabeled "Transfers out").
    rows = parse_nab_format(SAMPLE_CSV.encode(), filename="statement.csv")
    assert not hasattr(rows[0], "category")


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
