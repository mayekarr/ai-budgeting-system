from __future__ import annotations

import pandas as pd
import streamlit as st

from frontend.api_client import get_transactions
from frontend.categories import ALL_CATEGORIES, category_options, present_categories

st.set_page_config(page_title="Category Drill-in", layout="wide")
st.title("Category Drill-in")

date_from = st.session_state.get("drill_in_date_from")
date_to = st.session_state.get("drill_in_date_to")

try:
    # Fetched once, unfiltered — the category dropdown's own options and any selected-category
    # filtering are both derived from this single result set (Income included, unlike Overview's
    # spend-only chart), rather than a second server round trip per selection.
    all_transactions = get_transactions(category=None, date_from=date_from, date_to=date_to)
except Exception as exc:  # pylint: disable=broad-except
    st.error(f"Could not load transactions: {exc}")
    st.stop()

options = category_options(present_categories(all_transactions))
incoming_category = st.session_state.get("drill_in_category", ALL_CATEGORIES)

# Streamlit persists a widget's own session_state entry (by `key=`) across reruns and ignores
# `index=` once that entry exists — so a fresh handoff from Overview must be applied by writing
# directly into the widget's key, not just passed as `index`, or a prior selection on this page
# (from either an earlier Overview visit or the user's own dropdown change) would stick instead.
if st.session_state.get("_drill_in_last_seen_handoff") != incoming_category:
    st.session_state["drill_in_category_select"] = incoming_category if incoming_category in options else options[0]
    st.session_state["_drill_in_last_seen_handoff"] = incoming_category

selected_category = st.selectbox("Category", options, key="drill_in_category_select")

if selected_category == ALL_CATEGORIES:
    transactions = all_transactions
else:
    transactions = [t for t in all_transactions if t.get("category") == selected_category]

if not transactions:
    scope = f"for {selected_category} " if selected_category != ALL_CATEGORIES else ""
    st.info(f"No transactions found {scope}in the selected range.")
else:
    df = pd.DataFrame(transactions)

    def _flags(row: pd.Series) -> str:
        badges = []
        if row.get("is_refund"):
            badges.append("↩ refund")
        if row.get("transfer_group_id") is not None:
            badges.append("⇄ transfer")
        return " ".join(badges)

    df["flags"] = df.apply(_flags, axis=1)
    st.dataframe(
        df[["date", "raw_description", "amount", "subcategory", "flags"]],
        width="stretch",
    )
