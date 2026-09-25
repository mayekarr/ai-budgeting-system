from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from frontend.api_client import get_summary
from frontend.categories import category_options
from frontend.date_ranges import PRESETS, resolve_date_range

st.set_page_config(page_title="Overview", layout="wide")
st.title("Overview")

preset = st.selectbox("Date range", PRESETS, key="overview_date_preset")
date_from, date_to = resolve_date_range(preset, date.today())

if preset == "Custom":
    custom_range = st.date_input(
        "Custom range", value=(date_from, date_to), key="overview_custom_range"
    )
    if isinstance(custom_range, tuple) and len(custom_range) == 2:
        date_from, date_to = custom_range

try:
    summary = get_summary(date_from=date_from, date_to=date_to)
except Exception as exc:  # pylint: disable=broad-except
    st.error(f"Could not load summary: {exc}")
    st.stop()

col1, col2, col3 = st.columns(3)
col1.metric("Income", f"${summary['total_income']:,.2f}")
col2.metric("Expense", f"${summary['total_expense']:,.2f}")
col3.metric("Net", f"${summary['net']:,.2f}")

by_category = summary["by_category"]
by_income_category = summary["by_income_category"]

if not by_category and not by_income_category:
    st.info("No transactions in the selected range.")
else:
    if by_category:
        st.subheader("Spending by Category")
        chart_df = pd.DataFrame(by_category).set_index("category")
        st.bar_chart(chart_df["amount"], horizontal=True)

    if by_income_category:
        # Every income row shares category=Income (see GET /summary's docstring), so subcategory
        # -- Salary vs Dividends vs Tax Refund, ... -- is the meaningful breakdown for earnings,
        # not category. A separate chart from Spending by Category since the two aren't the same
        # grouping axis and mixing credits into a "net spend" chart would misread as spend.
        st.subheader("Earnings by Source")
        income_chart_df = pd.DataFrame(by_income_category).set_index("category")
        st.bar_chart(income_chart_df["amount"], horizontal=True)

    # "Income" is appended after the spend categories so the one selector/link below drills into
    # earnings too (Rohan's request) — reusing the existing mechanism rather than a second,
    # competing one that would race it for control of session_state["drill_in_category"]. Offered
    # even with $0 income in range (Drill-in already handles an empty selection gracefully).
    options = category_options([c["category"] for c in by_category] + ["Income"])
    selected_category = st.selectbox(
        "Drill into a category", options, key="overview_selected_category"
    )
    # Handed off to the Category Drill-in page via session_state; kept in sync every render so the
    # link below always reflects the current selection, no separate confirm step needed.
    st.session_state["drill_in_category"] = selected_category
    st.session_state["drill_in_date_from"] = date_from
    st.session_state["drill_in_date_to"] = date_to
    st.page_link("pages/2_Category_Drill_in.py", label="Go to Category Drill-in →")
