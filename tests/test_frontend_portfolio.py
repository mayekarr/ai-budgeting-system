from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

_DASHBOARD_PATH = Path(__file__).resolve().parent.parent / "frontend" / "dashboard.py"


def _fake_assets(*args, **kwargs):
    return {
        "assets": [
            {"id": 1, "name": "Jericho Ct", "type": "Real Estate", "is_active": True,
             "income": 2704.86, "expense": 4877.79, "net": -2172.93},
            {"id": 2, "name": "Share Portfolio", "type": "Shares", "is_active": True,
             "income": 0.0, "expense": 3847.91, "net": -3847.91},
        ],
        "total": {"income": 2704.86, "expense": 8725.70, "net": -6020.84},
    }


def _fake_asset_transactions(asset_id, date_from=None, date_to=None):
    rows = {
        1: [{"id": 10, "date": "2026-08-05", "amount": 2704.86, "raw_description": "6 Jericho Ct rent",
             "category": "Income", "subcategory": "Rental Income", "asset_id": 1}],
        2: [{"id": 11, "date": "2026-07-31", "amount": -3847.91,
             "raw_description": "INTEREST CHARGED FROM A/C 34-189-2465",
             "category": "Loans & Finance", "subcategory": "Loan Interest", "asset_id": 2}],
    }
    return rows[asset_id]


def _open_portfolio() -> AppTest:
    # Through the real multipage entrypoint, same reasoning as tests/test_frontend_overview.py.
    at = AppTest.from_file(str(_DASHBOARD_PATH), default_timeout=15)
    at.run()
    at.switch_page("pages/4_Portfolio.py")
    return at


def _patched(assets=_fake_assets, transactions=_fake_asset_transactions):
    return (
        patch("frontend.api_client.get_assets", side_effect=assets),
        patch("frontend.api_client.get_asset_transactions", side_effect=transactions),
    )


def test_portfolio_shows_total_kpis_and_one_row_per_asset():
    p_assets, p_tx = _patched()
    with p_assets, p_tx:
        at = _open_portfolio()
        at.run()

    assert not at.exception
    assert [m.value for m in at.metric] == ["$2,704.86", "$8,725.70", "-$6,020.84"]
    table = at.dataframe[0].value
    assert list(table["Asset"]) == ["Jericho Ct", "Share Portfolio"]
    assert list(table["Net"]) == [-2172.93, -3847.91]


def test_portfolio_passes_the_resolved_date_range():
    p_assets, p_tx = _patched()
    with p_assets as mock_assets, p_tx as mock_tx:
        at = _open_portfolio()
        at.run()
        at.selectbox(key="portfolio_date_preset").select("Custom").run()
        at.date_input(key="portfolio_custom_range").set_value((date(2026, 7, 1), date(2026, 8, 31))).run()

    assert mock_assets.call_args.kwargs == {"date_from": date(2026, 7, 1), "date_to": date(2026, 8, 31)}
    assert mock_tx.call_args.kwargs == {"date_from": date(2026, 7, 1), "date_to": date(2026, 8, 31)}


def test_selecting_an_asset_shows_its_transactions():
    p_assets, p_tx = _patched()
    with p_assets, p_tx as mock_tx:
        at = _open_portfolio()
        at.run()
        at.selectbox(key="portfolio_asset_select").select("Share Portfolio").run()

    assert not at.exception
    assert mock_tx.call_args.args == (2,)
    drill_in = at.dataframe[1].value
    assert list(drill_in["Description"]) == ["INTEREST CHARGED FROM A/C 34-189-2465"]


def test_no_assets_shows_setup_hint_instead_of_empty_table():
    p_assets, p_tx = _patched(assets=lambda *a, **k: {"assets": [], "total": {"income": 0, "expense": 0, "net": 0}})
    with p_assets, p_tx as mock_tx:
        at = _open_portfolio()
        at.run()

    assert not at.exception
    assert "seed_assets" in at.info[0].value
    assert len(at.dataframe) == 0
    mock_tx.assert_not_called()


def test_api_failure_shows_error():
    def _boom(*args, **kwargs):
        raise RuntimeError("backend down")

    p_assets, p_tx = _patched(assets=_boom)
    with p_assets, p_tx:
        at = _open_portfolio()
        at.run()

    assert "backend down" in at.error[0].value
