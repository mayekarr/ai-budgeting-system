from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

_DASHBOARD_PATH = Path(__file__).resolve().parent.parent / "frontend" / "dashboard.py"


def _leg(id_, account, amount, desc, d="2026-08-10", account_id=1):
    return {"id": id_, "account_id": account_id, "account_name": account, "date": d, "amount": amount,
            "raw_description": desc}


def _fake_transfers(*args, **kwargs):
    return {
        "pairs": [
            {"group_id": 20, "detection_tier": 2, "confidence": 0.6, "date": "2026-08-10", "amount": 100.0,
             "legs": [_leg(3, "AC", -100.0, "LOOKS LIKE A TRANSFER"), _leg(4, "CC", 99.5, "UBER TRIP")]},
            {"group_id": 10, "detection_tier": 1, "confidence": 1.0, "date": "2026-06-01", "amount": 1000.0,
             "legs": [_leg(1, "JC", -1000.0, "JC to AC"), _leg(2, "AC", 1000.0, "AC from JC")]},
        ],
        "lone": [_leg(5, "CC", 500.0, "DIRECT DEBIT PAYMENT", d="2026-07-05")],
    }


def _fake_accounts(*args, **kwargs):
    return [{"id": 1, "name": "JC"}, {"id": 2, "name": "AC"}, {"id": 3, "name": "CC"}]


def _open() -> AppTest:
    # Through the real multipage entrypoint, same reasoning as tests/test_frontend_overview.py.
    at = AppTest.from_file(str(_DASHBOARD_PATH), default_timeout=15)
    at.run()
    at.switch_page("pages/5_Transfers.py")
    return at


def _patched(transfers=_fake_transfers):
    return (
        patch("frontend.api_client.get_transfers", side_effect=transfers),
        patch("frontend.api_client.get_accounts", side_effect=_fake_accounts),
    )


def test_page_shows_counts_of_pairs_tentative_pairs_and_lone_transfers():
    p_transfers, p_accounts = _patched()
    with p_transfers, p_accounts:
        at = _open()
        at.run()

    assert not at.exception
    assert [m.value for m in at.metric] == ["2", "1", "1"]
    pairs = at.dataframe[0].value
    assert list(pairs["Amount"]) == [100.0, 1000.0]
    assert list(pairs["Confidence"]) == ["Tentative (60%)", "Confident"]
    assert list(pairs["From"]) == ["AC", "JC"] and list(pairs["To"]) == ["CC", "AC"]
    lone = at.dataframe[1].value
    assert list(lone["Description"]) == ["DIRECT DEBIT PAYMENT"]


def test_default_range_is_the_last_12_months_and_all_time_sends_no_dates():
    p_transfers, p_accounts = _patched()
    with p_transfers as mock_get, p_accounts:
        at = _open()
        at.run()
        default_kwargs = dict(mock_get.call_args.kwargs)
        at.selectbox(key="transfers_date_preset").select("All time").run()
        all_time_kwargs = dict(mock_get.call_args.kwargs)

    assert not at.exception
    assert default_kwargs["date_from"] is not None and default_kwargs["date_to"] is not None
    assert default_kwargs["date_from"] < default_kwargs["date_to"] <= date.today()
    assert (all_time_kwargs["date_from"], all_time_kwargs["date_to"]) == (None, None)


def test_choosing_an_account_filters_by_its_id():
    p_transfers, p_accounts = _patched()
    with p_transfers as mock_get, p_accounts:
        at = _open()
        at.run()
        assert mock_get.call_args.kwargs["account_id"] is None
        at.selectbox(key="transfers_account").select("CC").run()

    assert not at.exception
    assert mock_get.call_args.kwargs["account_id"] == 3


def test_tentative_only_toggle_narrows_the_pairs_table():
    p_transfers, p_accounts = _patched()
    with p_transfers, p_accounts:
        at = _open()
        at.run()
        at.toggle(key="transfers_tentative_only").set_value(True).run()

    assert not at.exception
    assert list(at.dataframe[0].value["Confidence"]) == ["Tentative (60%)"]


def test_only_tentative_pairs_get_a_not_a_transfer_button_and_it_unlinks_via_the_first_leg():
    p_transfers, p_accounts = _patched()
    with p_transfers, p_accounts:
        at = _open()
        at.run()
        assert at.button(key="reject_pair_20") is not None
        assert not [b for b in at.button if b.key == "reject_pair_10"]          # confident: no button
        with patch("frontend.api_client.reject_transfer_match") as mock_reject:
            at.button(key="reject_pair_20").click().run()

    assert not at.exception
    mock_reject.assert_called_once_with(3)


def test_a_failed_unlink_shows_an_error_and_keeps_the_page():
    p_transfers, p_accounts = _patched()
    with p_transfers, p_accounts:
        at = _open()
        at.run()
        with patch("frontend.api_client.reject_transfer_match", side_effect=RuntimeError("boom")):
            at.button(key="reject_pair_20").click().run()

    assert not at.exception
    assert any("boom" in e.value for e in at.error)


def test_no_transfers_in_range_shows_an_info_message():
    p_transfers, p_accounts = _patched(lambda *a, **k: {"pairs": [], "lone": []})
    with p_transfers, p_accounts:
        at = _open()
        at.run()

    assert not at.exception
    assert any("No transfers" in i.value for i in at.info)


def test_api_failure_shows_an_error_instead_of_crashing():
    def boom(*a, **k):
        raise RuntimeError("backend down")

    p_transfers, p_accounts = _patched(boom)
    with p_transfers, p_accounts:
        at = _open()
        at.run()

    assert not at.exception
    assert any("backend down" in e.value for e in at.error)


def _with_a_three_leg_group(*args, **kwargs):
    data = _fake_transfers()
    data["pairs"].insert(0, {
        "group_id": 30, "detection_tier": 2, "confidence": 0.6, "date": "2026-09-01", "amount": 30.0,
        "legs": [_leg(6, "JC", -30.0, "Arvan food"), _leg(7, "CC", -29.6, "NANDOS BURWOOD"),
                 _leg(8, "AC", 30.0, "Arvan food")],
    })
    return data


def test_a_group_with_more_than_two_legs_is_flagged_and_all_its_legs_are_shown():
    p_transfers, p_accounts = _patched(_with_a_three_leg_group)
    with p_transfers, p_accounts:
        at = _open()
        at.run()

    assert not at.exception
    warnings = " ".join(w.value for w in at.warning)
    assert "more than two" in warnings and "1" in warnings
    pairs = at.dataframe[0].value
    assert list(pairs["Legs"]) == [3, 2, 2]
    shown = " ".join(m.value for m in at.markdown)
    assert "NANDOS BURWOOD" in shown          # the unrelated third leg is visible, not hidden


def test_no_warning_when_every_pair_has_two_legs():
    p_transfers, p_accounts = _patched()
    with p_transfers, p_accounts:
        at = _open()
        at.run()
    assert not at.warning
