from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

DB_URL = "sqlite:///finance.db"


def get_engine():
    """Create a SQLAlchemy engine for reading from the SQLite database."""
    return create_engine(DB_URL, connect_args={"check_same_thread": False})


def load_transactions_df() -> pd.DataFrame:
    """
    Load all transactions into a pandas DataFrame.

    Returns an empty DataFrame if no data is available.
    """
    engine = get_engine()
    with engine.connect() as conn:
        df = pd.read_sql(text("SELECT * FROM transactions"), conn)
    # Ensure date column is parsed as datetime
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def main() -> None:
    st.set_page_config(
        page_title="AI Personal Budgeting Dashboard",
        layout="wide",
    )

    st.title("AI Personal Budgeting and Expense Categorisation")

    st.markdown(
        "Upload your bank transactions via the backend API, "
        "then use this dashboard to explore your spending."
    )

    try:
        df = load_transactions_df()
    except Exception as exc:  # pylint: disable=broad-except
        st.error(f"Could not load transactions from database: {exc}")
        return

    if df.empty:
        st.info(
            "No transactions found. "
            "Import a CSV via the FastAPI backend, then refresh this page."
        )
        return

    # Sidebar filters
    st.sidebar.header("Filters")

    min_date: Optional[date] = df["date"].min()
    max_date: Optional[date] = df["date"].max()

    if min_date and max_date:
        start_date, end_date = st.sidebar.date_input(
            "Date range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )
        # Normalize to tuple when only a single date is selected.
        if isinstance(start_date, tuple) or isinstance(end_date, tuple):
            # Streamlit sometimes returns tuple; guard against that.
            start_date, end_date = min_date, max_date
        mask = (df["date"] >= start_date) & (df["date"] <= end_date)
        df = df.loc[mask]

    selected_category = st.sidebar.selectbox(
        "Category",
        options=["All"] + sorted(df["category"].fillna("Uncategorized").unique().tolist()),
    )
    if selected_category != "All":
        df = df[df["category"].fillna("Uncategorized") == selected_category]

    if df.empty:
        st.warning("No transactions match the selected filters.")
        return

    # High-level metrics
    expenses = df[df["amount"] < 0]
    income = df[df["amount"] > 0]

    total_spent = float(-expenses["amount"].sum()) if not expenses.empty else 0.0
    total_income = float(income["amount"].sum()) if not income.empty else 0.0

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Spending", f"${total_spent:,.2f}")
    col2.metric("Total Income", f"${total_income:,.2f}")
    col3.metric("Net Cash Flow", f"${(total_income - total_spent):,.2f}")

    # Charts
    st.subheader("Spending by Category")

    if not expenses.empty:
        # Group by category and take absolute sums for visual clarity.
        cat = (
            expenses.assign(
                category=expenses["category"].fillna("Uncategorized")
            )
            .groupby("category", as_index=False)["amount"]
            .sum()
        )
        cat["amount"] = cat["amount"].abs()
        cat = cat.sort_values("amount", ascending=False)

        st.bar_chart(
            data=cat.set_index("category")["amount"],
        )
    else:
        st.info("No expense transactions (negative amounts) found for selected filters.")

    # Detailed table
    st.subheader("Transactions")
    st.dataframe(
        df.sort_values(["date", "id"], ascending=[False, False]),
        use_container_width=True,
    )


if __name__ == "__main__":
    main()

