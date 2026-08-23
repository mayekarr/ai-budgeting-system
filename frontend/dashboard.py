from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="AI Personal Budgeting Dashboard", layout="wide")

st.title("AI Personal Budgeting and Expense Categorisation")
st.markdown(
    "Upload bank statements via the backend API (`POST /transactions/upload`), then use the pages "
    "in the sidebar to explore your spending."
)
st.page_link("pages/1_Overview.py", label="Go to Overview →")
