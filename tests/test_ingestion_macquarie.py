from __future__ import annotations

from datetime import date

import pytest

from ingestion.macquarie_format import MacquarieFormatError, parse_macquarie_format
from ingestion.nab_format import NabFormatError
from ingestion.statement_parser import parse_statement_with_report

HEADER = (
    "Transaction Date,Details,Account,Category,Subcategory,Tags,Notes,Debit,Credit,Balance,"
    "Original Description\n"
)
CMA = "Macquarie Cash Management Account"
ACCELERATOR = "Macquarie Cash Management Accelerator Account"

SAMPLE_CSV = (
    HEADER
    + f"2026-09-30,Macquarie Cma Interest Paid,{CMA},Income,Interest,,,,61.6,27054.45,MACQUARIE CMA INTEREST PAID\n"
    + f"2026-09-28,To Rohan Mayekar & Anila Rohan Mayekar - Receipt number: 75517537 BSB: 182500 A/C: 000942290974,"
    f"{CMA},Financial,Transfers,,,5100,,26992.85,To ROHAN MAYEKAR & ANILA ROHAN MAYEKAR -\n"
    + f"2026-09-28,Mr Rohan Ashok Mayekar Transfer To Mac A,{CMA},Financial,Transfers,,,,5100,32092.85,"
    "MR ROHAN ASHOK MAYEKAR transfer to mac a\n"
    + f"2026-08-14,Bpay To Alliance Wealth,{CMA},Financial,BPAY Payments,,,250,,100.00,BPAY TO ALLIANCE WEALTH\n"
)


def _parse(csv: str = SAMPLE_CSV):
    return parse_macquarie_format(csv.encode(), filename="MAC.csv")


def test_credit_is_positive_and_debit_is_negative():
    rows = _parse()

    assert [r.amount for r in rows] == [61.6, -5100.0, 5100.0, -250.0]


def test_date_balance_and_account_come_from_the_columns():
    first = _parse()[0]

    assert first.date == date(2026, 9, 30)
    assert first.balance == 27054.45
    # The export has no account number; the account's name is the only identifier it gives.
    assert first.account_identifier == CMA


def test_description_is_the_richer_details_text_so_account_numbers_survive():
    transfer_out = _parse()[1]

    assert "A/C: 000942290974" in transfer_out.raw_description


def test_description_falls_back_to_original_description_when_details_is_blank():
    csv = HEADER + f"2026-09-30,,{CMA},Income,Interest,,,,61.6,27054.45,MACQUARIE CMA INTEREST PAID\n"

    assert _parse(csv)[0].raw_description == "MACQUARIE CMA INTEREST PAID"


def test_bank_type_is_mapped_to_a_value_the_transfer_matcher_understands():
    interest, transfer_out, transfer_in, bpay = _parse()

    assert interest.raw_transaction_type == "INTEREST PAID"  # never a transfer leg
    assert transfer_out.raw_transaction_type == "TRANSFER DEBIT"
    assert transfer_in.raw_transaction_type == "TRANSFER CREDIT"
    assert bpay.raw_transaction_type == "BPAY"


def test_dividends_are_typed_so_they_can_never_pair():
    csv = HEADER + f"2026-05-01,Aqlt Dst,{CMA},Income,Dividends & Distributions,,,,12.5,40.00,AQLT DST 001348109967\n"

    assert _parse(csv)[0].raw_transaction_type == "DIVIDEND"


def test_macquaries_own_category_is_not_stored_as_a_bank_category():
    # Tier-2 pairing rejects any bank category outside NAB's transfer-like set, and Macquarie's
    # "Transfers" is not in it. Macquarie's label is a different vocabulary, so it must not be stored.
    assert all(r.raw_bank_category is None for r in _parse())


def test_rows_keep_file_order():
    assert [r.date for r in _parse()] == [date(2026, 9, 30), date(2026, 9, 28), date(2026, 9, 28), date(2026, 8, 14)]


def test_a_row_with_both_debit_and_credit_is_surfaced():
    csv = HEADER + f"2026-09-30,Odd,{CMA},Financial,Transfers,,,5,5,1.00,ODD\n"

    with pytest.raises(MacquarieFormatError):
        _parse(csv)


def test_a_row_with_neither_debit_nor_credit_is_surfaced():
    csv = HEADER + f"2026-09-30,Odd,{CMA},Financial,Transfers,,,,,1.00,ODD\n"

    with pytest.raises(MacquarieFormatError):
        _parse(csv)


def test_invalid_date_is_surfaced():
    csv = HEADER + f"not-a-date,Odd,{CMA},Financial,Transfers,,,5,,1.00,ODD\n"

    with pytest.raises(MacquarieFormatError):
        _parse(csv)


def test_missing_account_is_surfaced():
    csv = HEADER + "2026-09-30,Odd,,Financial,Transfers,,,5,,1.00,ODD\n"

    with pytest.raises(MacquarieFormatError):
        _parse(csv)


def test_missing_required_column_is_surfaced():
    with pytest.raises(MacquarieFormatError):
        _parse("Transaction Date,Details\n2026-09-30,x\n")


def test_zero_amount_rows_are_skipped_and_counted():
    csv = SAMPLE_CSV + f"2026-08-01,Notice,{CMA},Financial,Fees,,,0,,100.00,NOTICE\n"

    result = parse_statement_with_report(csv.encode(), filename="MAC.csv")

    assert len(result.rows) == 4
    assert result.zero_amount_skipped == 1


def test_macquarie_error_is_a_nab_format_error_so_the_upload_route_handles_it():
    assert issubclass(MacquarieFormatError, NabFormatError)


# --- format detection ---------------------------------------------------------------------------

NAB_CSV = (
    "Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On\n"
    "2026-08-08,-38.66,Card ending 2957,PURCHASE AUTHORISATION,HILLS MEATS,-4131.90,Services,Hills Meats,\n"
)


def test_dispatcher_sends_a_macquarie_file_to_the_macquarie_parser():
    result = parse_statement_with_report(SAMPLE_CSV.encode(), filename="MAC.csv")

    assert result.rows[0].account_identifier == CMA


def test_dispatcher_sends_a_nab_file_to_the_nab_parser():
    result = parse_statement_with_report(NAB_CSV.encode(), filename="AC.csv")

    assert result.rows[0].account_identifier == "Card ending 2957"


def test_dispatcher_reports_an_unknown_layout_as_a_format_error():
    with pytest.raises(NabFormatError):
        parse_statement_with_report(b"Foo,Bar\n1,2\n", filename="x.csv")


def test_accelerator_account_name_is_kept_distinct():
    csv = HEADER + f"2026-09-28,From Rohan Mayekar,{ACCELERATOR},Financial,Transfers,,,,5100,80997.56,From ROHAN\n"

    assert _parse(csv)[0].account_identifier == ACCELERATOR


# --- review fixes --------------------------------------------------------------------------------

@pytest.mark.parametrize("debit, credit", [("-5", ""), ("", "-5")])
def test_a_negative_debit_or_credit_is_surfaced_not_sign_flipped(debit, credit):
    csv = HEADER + f"2026-09-30,Odd,{CMA},Financial,Transfers,,,{debit},{credit},1.00,ODD\n"

    with pytest.raises(MacquarieFormatError, match="negative"):
        _parse(csv)


def test_an_unreadable_file_is_not_reported_as_a_nab_export():
    with pytest.raises(NabFormatError) as excinfo:
        parse_statement_with_report(b"\x00\x01\x02 not a workbook", filename="MAC.xlsx")

    assert "NAB-style" not in str(excinfo.value)


def test_the_file_is_read_once_whichever_parser_handles_it(monkeypatch):
    import pandas as pd

    reads = []
    real = pd.read_csv
    monkeypatch.setattr(pd, "read_csv", lambda *a, **k: reads.append(1) or real(*a, **k))

    parse_statement_with_report(SAMPLE_CSV.encode(), filename="MAC.csv")
    parse_statement_with_report(NAB_CSV.encode(), filename="AC.csv")

    assert len(reads) == 2   # one per file, not two


def test_a_block_repeated_at_an_export_seam_is_dropped_and_counted():
    # Same defect the NAB export has (FR-9k): the block just after a page seam copies the block just before.
    def line(day, month, n):
        return f"2026-{month:02d}-{day:02d},Payment {n},{CMA},Financial,Transfers,,,{n}.00,,,PAYMENT {n}\n"

    block = [line(d, 3, d) for d in range(10, 0, -1)]            # 10 rows, newest first
    newer = [line(d, 4, d) for d in range(20, 10, -1)]
    older = [line(d, 2, d) for d in range(5, 0, -1)]
    csv = HEADER + "".join(newer + block + block + older)

    result = parse_statement_with_report(csv.encode(), filename="MAC.csv")

    assert result.seam_repeats_dropped == 10
    assert len(result.rows) == len(newer) + len(block) + len(older)


def test_interest_and_dividend_rows_carry_a_category_hint_and_other_rows_do_not():
    csv = (
        HEADER
        + f"2026-09-30,Interest,{CMA},Income,Interest,,,,61.6,1.00,I\n"
        + f"2026-05-01,Dst,{CMA},Income,Dividends & Distributions,,,,12.5,1.00,D\n"
        + f"2026-05-02,Pay,{CMA},Financial,BPAY Payments,,,30,,1.00,P\n"
    )

    interest, dividend, bpay = _parse(csv)

    assert interest.category_hint == ("Income", "Interest")
    assert dividend.category_hint == ("Income", "Dividends & Distributions")
    assert bpay.category_hint is None


def test_a_csv_saved_with_a_utf8_bom_still_parses():
    # 'CSV UTF-8' exports start with an invisible byte-order mark that otherwise sticks to the first header.
    macquarie = parse_statement_with_report(("﻿" + SAMPLE_CSV).encode("utf-8"), filename="MAC.csv")
    nab = parse_statement_with_report(("﻿" + NAB_CSV).encode("utf-8"), filename="AC.csv")

    assert len(macquarie.rows) == 4 and len(nab.rows) == 1


def test_original_description_is_optional_because_details_already_carries_the_text():
    csv = (
        "Transaction Date,Details,Account,Category,Subcategory,Debit,Credit,Balance\n"
        f"2026-09-30,Macquarie Cma Interest Paid,{CMA},Income,Interest,,61.6,27054.45\n"
    )

    (row,) = _parse(csv)

    assert row.raw_description == "Macquarie Cma Interest Paid"


def test_new_ingestion_modules_have_a_real_docstring():
    import ingestion.macquarie_format as macquarie
    import ingestion.statement_parser as dispatcher

    assert macquarie.__doc__ and dispatcher.__doc__
