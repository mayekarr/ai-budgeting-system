from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from frontend.api_client import get_asset_transactions, get_assets
from frontend.date_ranges import PRESETS, resolve_date_range

st.set_page_config(page_title="Portfolio", layout="wide")
st.title("Portfolio")

preset = st.selectbox("Date range", PRESETS, key="portfolio_date_preset")
date_from, date_to = resolve_date_range(preset, date.today())

if preset == "Custom":
    custom_range = st.date_input(
        "Custom range", value=(date_from, date_to), key="portfolio_custom_range"
    )
    if isinstance(custom_range, tuple) and len(custom_range) == 2:
        date_from, date_to = custom_range

try:
    portfolio = get_assets(date_from=date_from, date_to=date_to)
except Exception as exc:  # pylint: disable=broad-except
    st.error(f"Could not load assets: {exc}")
    st.stop()

assets = portfolio["assets"]
if not assets:
    st.info(
        "No assets set up yet. Copy `config/assets.example.json` to `config/assets.local.json`, "
        "fill it in, then run `python -m scripts.seed_assets`."
    )
    st.stop()

total = portfolio["total"]
col1, col2, col3 = st.columns(3)
col1.metric("Income", f"${total['income']:,.2f}")
col2.metric("Expense", f"${total['expense']:,.2f}")
# Net is often negative here (loan interest outweighing rent), so format the sign explicitly
# rather than letting "$-6,020.84" through.
net = total["net"]
col3.metric("Net", f"-${-net:,.2f}" if net < 0 else f"${net:,.2f}")

st.dataframe(
    pd.DataFrame(
        {
            "Asset": [a["name"] for a in assets],
            "Type": [a["type"] for a in assets],
            "Income": [a["income"] for a in assets],
            "Expense": [a["expense"] for a in assets],
            "Net": [a["net"] for a in assets],
        }
    ),
    hide_index=True,
)

ALL_ASSETS = "All Assets"
asset_ids = {a["name"]: a["id"] for a in assets}
selected = st.selectbox(
    "Asset transactions", [ALL_ASSETS] + list(asset_ids), key="portfolio_asset_select"
)
names_to_show = list(asset_ids) if selected == ALL_ASSETS else [selected]

# "All Assets" reuses the per-asset endpoint, one cached call per asset -- a handful of assets, so
# not worth a separate combined endpoint.
transactions = []
for name in names_to_show:
    try:
        rows = get_asset_transactions(asset_ids[name], date_from=date_from, date_to=date_to)
    except Exception as exc:  # pylint: disable=broad-except
        st.error(f"Could not load transactions for {name}: {exc}")
        st.stop()
    transactions.extend({**t, "_asset": name} for t in rows)
transactions.sort(key=lambda t: t["date"], reverse=True)

if not transactions:
    st.info(f"No transactions for {selected} in the selected range.")
else:
    columns = {
        "Date": [t["date"] for t in transactions],
        "Description": [t["raw_description"] for t in transactions],
        "Category": [t["category"] for t in transactions],
        "Subcategory": [t["subcategory"] for t in transactions],
        "Amount": [t["amount"] for t in transactions],
    }
    if selected == ALL_ASSETS:
        columns = {"Asset": [t["_asset"] for t in transactions], **columns}
    st.dataframe(pd.DataFrame(columns), hide_index=True)
