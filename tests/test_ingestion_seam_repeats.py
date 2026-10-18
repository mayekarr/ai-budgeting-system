from __future__ import annotations

from datetime import date, timedelta

from ingestion.nab_format import ParsedRow, parse_nab_format, parse_nab_format_with_report
from ingestion.seam_repeats import MIN_BLOCK, drop_seam_repeats

START = date(2025, 1, 31)


def _row(day_offset: int, n: int, *, balance: float | None = None, amount: float | None = None) -> ParsedRow:
    """A distinct row per `n`; `day_offset` days before START (newest-first files descend)."""
    return ParsedRow(
        date=START - timedelta(days=day_offset),
        amount=amount if amount is not None else -(10.0 + n),
        account_identifier="Card ending 7128",
        raw_transaction_type="PURCHASE",
        raw_description=f"MERCHANT {n}",
        balance=balance,
    )


def _newest_first(count: int, start_n: int = 0) -> list[ParsedRow]:
    # Two rows per day, so same-day neighbours exist (like real card data).
    return [_row(i // 2, start_n + i) for i in range(count)]


def _with_seam_repeat(rows: list[ParsedRow], seam: int, block: int) -> list[ParsedRow]:
    """Mimic the export fault: the `block` rows before `seam` are re-listed right after it, but
    the export then continues with the rows that followed -- the copy sits *between* them."""
    copy = [
        ParsedRow(**{**r.__dict__, "balance": (r.balance or 0) + 1})  # copy carries different balances
        for r in rows[seam - block : seam]
    ]
    return rows[:seam] + copy + rows[seam:]


def test_drops_a_block_repeated_in_place_at_a_date_order_break():
    # Real fault shape: rows[seam-k:seam] re-listed at rows[seam:seam+k]. For the date to break
    # order there, the copied block must start newer than the row before the seam.
    base = _newest_first(200)
    seam, block = 100, 30
    faulty = base[:seam] + base[seam - block : seam] + base[seam:]

    kept, dropped = drop_seam_repeats(faulty)

    assert kept == base
    assert dropped == base[seam - block : seam]


def test_copy_with_different_running_balances_is_still_dropped():
    base = _newest_first(120)
    faulty = _with_seam_repeat(base, seam=60, block=25)

    kept, dropped = drop_seam_repeats(faulty)

    assert kept == base
    assert len(dropped) == 25


def test_every_seam_in_a_file_is_handled():
    base = _newest_first(400)
    faulty = base
    # Insert from the back so earlier seam indices stay valid.
    for seam in (300, 200, 100):
        faulty = faulty[:seam] + faulty[seam - 20 : seam] + faulty[seam:]

    kept, dropped = drop_seam_repeats(faulty)

    assert kept == base
    assert len(dropped) == 60


def test_oldest_first_files_are_handled_too():
    base = list(reversed(_newest_first(120)))
    seam, block = 60, 20
    faulty = base[:seam] + base[seam - block : seam] + base[seam:]

    kept, dropped = drop_seam_repeats(faulty)

    assert kept == base
    assert len(dropped) == block


def test_genuine_same_day_repeat_purchases_are_never_dropped():
    # Identical coffee bought several times in a day: 1-8 rows apart, no date-order break.
    base = _newest_first(60)
    coffee = _row(5, 999)
    rows = base[:10] + [coffee, coffee] + base[10:20] + [coffee] + base[20:]

    kept, dropped = drop_seam_repeats(rows)

    assert kept == rows
    assert dropped == []


def test_short_identical_run_straddling_a_date_break_is_kept():
    # A genuine repeat that happens to sit right at a date break, but far shorter than a
    # page-seam block: must survive.
    base = _newest_first(100)
    seam = 50
    short = MIN_BLOCK - 1
    rows = base[:seam] + base[seam - short : seam] + base[seam:]

    kept, dropped = drop_seam_repeats(rows)

    assert kept == rows
    assert dropped == []


def test_near_miss_block_is_kept_entirely():
    # One row of the "copy" differs in amount -> not a verbatim copy -> drop nothing.
    base = _newest_first(120)
    seam, block = 60, 30
    copy = list(base[seam - block : seam])
    copy[10] = _row(0, 0, amount=-0.01)
    rows = base[:seam] + copy + base[seam:]

    kept, dropped = drop_seam_repeats(rows)

    assert kept == rows
    assert dropped == []


def test_repeated_block_without_a_date_order_break_is_kept():
    # Same-date rows throughout: the copy doesn't break date order, so there is no seam evidence.
    block = [_row(0, n) for n in range(MIN_BLOCK + 5)]
    rows = block + block

    kept, dropped = drop_seam_repeats(rows)

    assert kept == rows
    assert dropped == []


def test_empty_and_tiny_inputs_pass_through():
    assert drop_seam_repeats([]) == ([], [])
    one = [_row(0, 1)]
    assert drop_seam_repeats(one) == (one, [])


def test_parser_drops_the_repeat_for_a_file_crossing_the_1000_row_limit():
    # AC/RC-shaped (NAB columns) export that crosses 1,000 rows: the export tool repeats the block
    # that ended page 1 at the start of page 2.
    base = _newest_first(1100)
    seam, block = 1000, 40
    faulty = base[:seam] + base[seam - block : seam] + base[seam:]
    lines = ["Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On"]
    for r in faulty:
        lines.append(f"{r.date.isoformat()},{r.amount},{r.account_identifier},{r.raw_transaction_type},{r.raw_description},0,,,")
    raw = ("\n".join(lines) + "\n").encode()

    parsed = parse_nab_format(raw, filename="AC.csv")

    assert len(parsed) == 1100
    assert [p.raw_description for p in parsed] == [r.raw_description for r in base]


# --- balance recomputation -------------------------------------------------------------------
# The export's Balance column is computed over the stitched rows (verified against the bank's PDF
# statements, FR-9k), so once copies are dropped the surviving balances are wrong. They are
# recomputed backward from the newest row's balance, which is the one value known to be right.

def _chain(rows: list[ParsedRow], newest_balance: float, *, newest_first: bool) -> list[ParsedRow]:
    """Assign a consistent running balance over `rows` as the export would (anchored on newest)."""
    out = list(rows)
    order = range(len(out)) if newest_first else range(len(out) - 1, -1, -1)
    bal = newest_balance
    for i in order:
        out[i] = ParsedRow(**{**out[i].__dict__, "balance": round(bal, 2)})
        bal -= out[i].amount
    return out


def test_balances_are_recomputed_backward_from_the_newest_row_after_a_drop():
    base = _newest_first(120)
    seam, block = 60, 25
    faulty = _chain(base[:seam] + base[seam - block : seam] + base[seam:], -1000.0, newest_first=True)

    kept, dropped = drop_seam_repeats(faulty)

    assert len(dropped) == block
    assert [r.balance for r in kept] == [r.balance for r in _chain(base, -1000.0, newest_first=True)]
    assert kept[0].balance == -1000.0  # the anchor is untouched


def test_balances_are_recomputed_for_oldest_first_files_anchored_on_the_last_row():
    base = list(reversed(_newest_first(120)))
    seam, block = 60, 20
    faulty = _chain(base[:seam] + base[seam - block : seam] + base[seam:], -1000.0, newest_first=False)

    kept, _ = drop_seam_repeats(faulty)

    assert [r.balance for r in kept] == [r.balance for r in _chain(base, -1000.0, newest_first=False)]
    assert kept[-1].balance == -1000.0


def test_balances_are_left_alone_when_nothing_is_dropped():
    # Without a seam repeat the bank's own balances are trusted as-is, even if they look odd.
    base = _newest_first(60)
    rows = [ParsedRow(**{**r.__dict__, "balance": 12345.67}) for r in base]

    kept, dropped = drop_seam_repeats(rows)

    assert dropped == []
    assert [r.balance for r in kept] == [12345.67] * 60


def test_missing_anchor_balance_leaves_balances_as_none():
    base = _newest_first(120)
    faulty = base[:60] + base[35:60] + base[60:]

    kept, _ = drop_seam_repeats(faulty)

    assert all(r.balance is None for r in kept)


# --- review fixes (2026-10-18) ---------------------------------------------------------------

def test_file_with_many_order_breaks_is_scanned_quickly_and_nothing_is_dropped():
    # Not date-sorted at all (alternating dates): an order break at nearly every row. The matcher
    # must reject each break in O(1) rather than slicing for every block length.
    import time

    rows = [_row(0 if i % 2 else 3, i) for i in range(3000)]

    started = time.perf_counter()
    kept, dropped = drop_seam_repeats(rows)

    assert time.perf_counter() - started < 1.0
    assert kept == rows
    assert dropped == []


def test_balances_are_left_alone_when_the_newest_end_does_not_chain():
    # Safety check on the anchor: if the rows the fault can't have touched don't chain
    # (balance - amount != next balance), the file's convention isn't what we assumed, so the
    # recompute is skipped rather than overwriting bank values with a wrong chain.
    base = _newest_first(120)
    seam, block = 60, 25
    faulty = base[:seam] + base[seam - block : seam] + base[seam:]
    faulty = [ParsedRow(**{**r.__dict__, "balance": 500.0 + i}) for i, r in enumerate(faulty)]

    kept, dropped = drop_seam_repeats(faulty)

    assert len(dropped) == block  # the drop itself still happens
    assert [r.balance for r in kept] == [r.balance for r in faulty[:seam]] + [
        r.balance for r in faulty[seam + block :]
    ]


def test_rows_without_a_balance_stay_without_one_after_a_recompute():
    base = _newest_first(120)
    seam, block = 60, 25
    faulty = _chain(base[:seam] + base[seam - block : seam] + base[seam:], -1000.0, newest_first=True)
    # A kept row (older than the seam) that the bank gave no balance for.
    faulty[100] = ParsedRow(**{**faulty[100].__dict__, "balance": None})

    kept, _ = drop_seam_repeats(faulty)

    no_balance = [r for r in kept if r.balance is None]
    assert len(no_balance) == 1
    assert no_balance[0].raw_description == faulty[100].raw_description
    assert sum(1 for r in kept if r.balance is not None) == len(kept) - 1


def test_parse_report_exposes_how_many_rows_were_dropped():
    base = _newest_first(1100)
    seam, block = 1000, 40
    faulty = base[:seam] + base[seam - block : seam] + base[seam:]
    lines = ["Date,Amount,Account Number,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On"]
    for r in faulty:
        lines.append(f"{r.date.isoformat()},{r.amount},{r.account_identifier},{r.raw_transaction_type},{r.raw_description},0,,,")
    raw = ("\n".join(lines) + "\n").encode()

    result = parse_nab_format_with_report(raw, filename="AC.csv")

    assert len(result.rows) == 1100
    assert result.seam_repeats_dropped == 40


# --- second review round (2026-10-18) ---------------------------------------------------------

def test_oldest_first_file_ending_in_a_repeat_anchors_on_the_last_kept_row():
    # The anchor must never be a dropped row: its balance came from the stitched rows and is wrong.
    base = _chain(list(reversed(_newest_first(120))), -1000.0, newest_first=False)
    block = 20
    wrong_copy = [ParsedRow(**{**r.__dict__, "balance": 777.0}) for r in base[-block:]]

    kept, dropped = drop_seam_repeats(base + wrong_copy)

    assert dropped == wrong_copy
    assert kept == base
    assert kept[-1].balance == -1000.0


def test_log_counts_adjacent_dropped_blocks_separately(caplog):
    base = _newest_first(120)
    rows = base[:50] + base[30:50] + base[30:50] + base[50:]

    with caplog.at_level("WARNING", logger="ingestion.seam_repeats"):
        kept, dropped = drop_seam_repeats(rows)

    assert kept == base
    assert len(dropped) == 40
    assert "2 block(s)" in caplog.text
