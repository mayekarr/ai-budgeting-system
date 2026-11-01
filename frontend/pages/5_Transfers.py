from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from frontend.api_client import get_accounts, get_transfers, reject_transfer_match
from frontend.date_ranges import PRESETS, resolve_date_range

st.set_page_config(page_title="Transfers", layout="wide")
st.title("Transfers")
st.caption(
    "Money moving between your own accounts. Transfers are left out of income and spending, so "
    "this is the one place to check them. A transfer is an exact-amount move between your own accounts. "
    "A pair is Confident when an account number or reference links it; the rest were matched on the "
    "exact amount and date alone, and are marked Check when the two sides share no wording."
)

ALL_TIME = "All time"
if message := st.session_state.pop("_transfers_success", None):
    st.success(message)

preset = st.selectbox(
    "Date range",
    [ALL_TIME] + PRESETS,
    index=1 + PRESETS.index("Last 12 Months"),
    key="transfers_date_preset",
)
if preset == ALL_TIME:
    date_from = date_to = None
else:
    date_from, date_to = resolve_date_range(preset, date.today())
    if preset == "Custom":
        custom_range = st.date_input("Custom range", value=(date_from, date_to), key="transfers_custom_range")
        if isinstance(custom_range, tuple) and len(custom_range) == 2:
            date_from, date_to = custom_range

try:
    accounts = get_accounts()
except Exception as exc:  # pylint: disable=broad-except
    st.error(f"Could not load accounts: {exc}")
    accounts = []
ALL_ACCOUNTS = "All accounts"
account_ids = {a["name"]: a["id"] for a in accounts}
selected_account = st.selectbox("Account", [ALL_ACCOUNTS] + list(account_ids), key="transfers_account")
account_id = account_ids.get(selected_account)

try:
    data = get_transfers(date_from=date_from, date_to=date_to, account_id=account_id)
except Exception as exc:  # pylint: disable=broad-except
    st.error(f"Could not load transfers: {exc}")
    st.stop()

pairs, lone = data["pairs"], data["lone"]
if not pairs and not lone:
    st.info("No transfers in the selected range.")
    st.stop()


def _is_tentative(pair: dict) -> bool:
    return pair["confidence"] < 1.0


def _confidence_label(pair: dict) -> str:
    if _is_tentative(pair):
        return f"Check: tentative ({round(pair['confidence'] * 100)}%)"
    return "Check: no shared wording" if pair.get("needs_check") else "Confident"


# A group with more than two legs is never right, whatever the matcher thought of it.
to_check = [p for p in pairs if p.get("needs_check") or len(p["legs"]) > 2]
multi_leg_pairs = [p for p in pairs if len(p["legs"]) > 2]
if multi_leg_pairs:
    st.warning(
        f"{len(multi_leg_pairs)} group(s) have more than two legs. A move between two accounts has two, so "
        "an extra row (a shop purchase, a salary credit) has probably been attached to a real pair and is "
        "missing from your income or spending. They are marked in the table below and all their legs are "
        "listed under Check these pairs."
    )
col1, col2, col3 = st.columns(3)
col1.metric("Paired transfers", len(pairs))
col2.metric("Pairs to check", len(to_check))
col3.metric("Lone transfers", len(lone))

st.subheader("Paired transfers")
check_only = st.toggle("Pairs to check only", key="transfers_check_only")
shown = to_check if check_only else pairs
if shown:
    st.dataframe(
        pd.DataFrame(
            {
                "Date": [p["date"] for p in shown],
                "From": [p["legs"][0]["account_name"] for p in shown],
                "To": [p["legs"][-1]["account_name"] for p in shown],
                "Amount": [p["amount"] for p in shown],
                "Legs": [len(p["legs"]) for p in shown],
                "Confidence": [_confidence_label(p) for p in shown],
                "Description": [p["legs"][0]["raw_description"] for p in shown],
            }
        ),
        hide_index=True,
    )
else:
    st.caption("No pairs to show.")

if to_check:
    st.subheader("Check these pairs")
    st.caption(
        "These were matched on the exact amount and date alone and look doubtful (a transfer paired "
        "with an unrelated payment, for example). Unlinking a wrong pair puts both rows back into your totals."
    )
    for pair in to_check:
        out_leg, in_leg = pair["legs"][0], pair["legs"][-1]
        text_col, button_col = st.columns([5, 1])
        legs_text = "  ↔  ".join(
            f"{leg['account_name']}: {leg['raw_description']} (${leg['amount']:,.2f})" for leg in pair["legs"]
        )
        text_col.write(f"**{pair['date']}** · {legs_text}")
        if len(pair["legs"]) > 2:
            text_col.caption(
                "More than two legs: unlinking releases every leg, including any genuine pair in this group."
            )
        if button_col.button("Not a transfer", key=f"reject_pair_{pair['group_id']}"):
            try:
                # Rejecting any leg unlinks the whole group and puts every leg back to Income/Expense.
                reject_transfer_match(out_leg["id"])
                st.session_state["_transfers_success"] = (
                    f"Unlinked {out_leg['raw_description']!r} and {in_leg['raw_description']!r}."
                )
                st.rerun()
            except Exception as exc:  # pylint: disable=broad-except
                st.error(f"Could not unlink the pair: {exc}")

st.subheader("Lone transfers")
st.caption("The other side isn't imported (for example a card payment whose card statement ends earlier).")
if lone:
    st.dataframe(
        pd.DataFrame(
            {
                "Date": [leg["date"] for leg in lone],
                "Account": [leg["account_name"] for leg in lone],
                "Amount": [leg["amount"] for leg in lone],
                "Description": [leg["raw_description"] for leg in lone],
            }
        ),
        hide_index=True,
    )
else:
    st.caption("None in this range.")
