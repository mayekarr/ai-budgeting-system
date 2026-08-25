from __future__ import annotations

import pandas as pd
import streamlit as st

from categorisation.taxonomy import CATEGORIES, TAXONOMY
from frontend.api_client import correct_transaction_category, get_transactions
from frontend.categories import ALL_CATEGORIES, category_options, present_categories

st.set_page_config(page_title="Category Drill-in", layout="wide")
st.title("Category Drill-in")

# Set by the correction handler below, then this page reruns (st.rerun()) so the table's own fetch
# reflects the correction — the fetch a few lines down always runs before the button handler even
# sees the click, so within that one run it's inherently stale. The success message can't just be
# shown inline there, since a rerun restarts the script from the top before it would render.
if "_drill_in_correction_success" in st.session_state:
    st.success(st.session_state.pop("_drill_in_correction_success"))

date_from = st.session_state.get("drill_in_date_from")
date_to = st.session_state.get("drill_in_date_to")

try:
    # Fetched once, unfiltered by category — the category dropdown's own options and any
    # selected-category filtering are both derived from this single result set (Income included,
    # unlike Overview's spend-only chart), rather than a second server round trip per selection.
    fetched = get_transactions(category=None, date_from=date_from, date_to=date_to)
except Exception as exc:  # pylint: disable=broad-except
    st.error(f"Could not load transactions: {exc}")
    st.stop()

# FR-9c/FR-13: Transfer rows are structurally excluded from category breakdowns, and FR-14's
# drill-in shows that same breakdown's underlying transactions — GET /transactions itself doesn't
# filter this (unlike GET /summary), and transfer detection never clears a transfer's pre-transfer
# category, so without this filter a transfer could appear under an ordinary spend category here
# even though it was never counted in that category's Overview total. superseded_by_id mirrors
# GET /summary's own exclusion: a settled row's now-resolved pending counterpart would otherwise
# show as a second, duplicate-looking transaction for the same real-world charge.
all_transactions = [
    t for t in fetched if t.get("type") != "Transfer" and t.get("superseded_by_id") is None
]

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
        # No transfer badge: Transfer-typed rows are filtered out above, so transfer_group_id is
        # always None here — nothing left for it to flag.
        return "↩ refund" if row.get("is_refund") else ""

    df["flags"] = df.apply(_flags, axis=1)
    st.dataframe(
        df[["date", "raw_description", "amount", "subcategory", "flags"]],
        width="stretch",
    )

    # J4/FR-9/FR-15: correct one of the rows currently shown above; the correction also writes
    # back a CategorisationRule (backend/api.py) so a future transaction with the same raw
    # description auto-categorises the same way instead of repeating the same mistake.
    st.subheader("Correct a transaction's category")

    def _tx_label(tx_id: int) -> str:
        tx = next(t for t in transactions if t["id"] == tx_id)
        return f"{tx['date']} · {tx['raw_description']} · ${tx['amount']:.2f}"

    selected_tx_id = st.selectbox(
        "Transaction", [t["id"] for t in transactions],
        format_func=_tx_label, key="drill_in_correction_tx_select",
    )

    selected_correction_category = st.selectbox(
        "New category", CATEGORIES, key="drill_in_correction_category_select"
    )

    # A category change can leave the subcategory widget's persisted key value outside the new
    # category's option list (e.g. switching to a category with fewer/no subcategories) — reset it
    # explicitly, same pattern as the category-filter selectbox above.
    if st.session_state.get("_drill_in_correction_last_seen_category") != selected_correction_category:
        st.session_state["drill_in_correction_subcategory_select"] = ""
        st.session_state["_drill_in_correction_last_seen_category"] = selected_correction_category

    selected_correction_subcategory = st.selectbox(
        "New subcategory", [""] + TAXONOMY[selected_correction_category],
        key="drill_in_correction_subcategory_select",
    )

    if st.button("Save correction", key="drill_in_save_correction_button"):
        try:
            correct_transaction_category(
                selected_tx_id,
                category=selected_correction_category,
                subcategory=selected_correction_subcategory or None,
            )
            st.session_state["_drill_in_correction_success"] = (
                f"Transaction {selected_tx_id} updated to {selected_correction_category}."
            )
            st.rerun()
        except Exception as exc:  # pylint: disable=broad-except
            st.error(f"Could not save correction: {exc}")
