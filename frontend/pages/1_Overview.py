from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from frontend.api_client import get_summary, get_summary_by_year
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


def _render_tax_refund_yoy() -> None:
    """
    J7: ATO tax refunds year on year. Deliberately ignores the date range -- year-on-year only
    means something across every year -- and is rendered even when the monthly summary fails or the
    range is empty, since it depends on neither. Tax refunds are plain Income (the §4.2
    exception), so this is a direct sum, no netting.
    """
    st.divider()
    if st.toggle("Tax refund (year on year)", key="overview_tax_refund_yoy"):
        try:
            yearly = get_summary_by_year("Income", "Tax Refund")
        except Exception as exc:  # pylint: disable=broad-except
            st.error(f"Could not load tax refunds: {exc}")
        else:
            if not yearly:
                st.info(
                    "No tax refunds recorded yet. Current statements only go back to April 2026; "
                    "earlier years arrive with the historical backfill (J8)."
                )
            else:
                st.caption("All years, regardless of the date range above. Grouped by the year received.")
                # Year as text so the chart axis reads "2021", not "2,021".
                yearly_df = pd.DataFrame(
                    {
                        "Year": [str(y["year"]) for y in yearly],
                        "Tax refund": [y["amount"] for y in yearly],
                    }
                )
                st.bar_chart(yearly_df.set_index("Year")["Tax refund"])
                st.dataframe(yearly_df, hide_index=True)


try:
    summary = get_summary(date_from=date_from, date_to=date_to)
except Exception as exc:  # pylint: disable=broad-except
    st.error(f"Could not load summary: {exc}")
    _render_tax_refund_yoy()
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

_render_tax_refund_yoy()
