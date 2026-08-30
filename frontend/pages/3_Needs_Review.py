from __future__ import annotations

import streamlit as st

from backend.needs_review_reasons import (
    LOW_CONFIDENCE_CATEGORY,
    REFUND_AMBIGUITY,
    TRANSFER_MATCH,
    UNRECOGNISED_ACCOUNT,
)
from frontend.api_client import (
    confirm_transfer_match,
    confirm_transfer_with_id,
    correct_transaction_category,
    correct_transaction_is_refund,
    get_suggested_transfer_match,
    get_transactions,
    reject_transfer_match,
)
from frontend.category_correction import render_category_correction_widget

st.set_page_config(page_title="Needs Review", layout="wide")
st.title("Needs Review")

# One combined queue (J5, docs/design-logic-and-ux.md §3.2): FR-10 low-confidence categorisation,
# an unrecognised new account (ingestion/account_resolution.py), an ambiguous refund signal
# (§1.2), and a Tier-2 transfer match (§2.3) all land here, filterable by reason rather than split
# across separate pages.
REASON_LABELS = {
    LOW_CONFIDENCE_CATEGORY: "Low-confidence category",
    UNRECOGNISED_ACCOUNT: "Unrecognised account",
    REFUND_AMBIGUITY: "Refund ambiguity",
    TRANSFER_MATCH: "Transfer match",
}
ALL_REASONS_LABEL = "All reasons"

# Same pattern as Category Drill-in's success-after-rerun handling: the action handlers below
# call st.rerun() so the queue reflects the change immediately, and a rerun restarts the script
# from the top before an inline success message would render — so it's stashed and shown here.
if "_review_action_success" in st.session_state:
    st.success(st.session_state.pop("_review_action_success"))


def _reason_label(reason: str | None) -> str:
    return REASON_LABELS.get(reason, reason or "Unknown")


def _row_header(tx: dict) -> None:
    st.write(f"**{tx['date']} · {tx['raw_description']} · ${tx['amount']:.2f}**")
    st.caption(_reason_label(tx.get("needs_review_reason")))


def _render_transfer_match(tx: dict) -> None:
    tx_id = tx["id"]
    if tx.get("transfer_group_id") is not None:
        # Tier-2 Medium: already auto-linked as Transfer — a soft, non-blocking confirmation.
        # Show the other leg(s), not just the bare group id, so the user isn't confirming blind
        # (/code-review finding — GET /transactions?transfer_group_id=... exists exactly for this).
        try:
            group_members = get_transactions(transfer_group_id=tx["transfer_group_id"])
        except Exception as exc:  # pylint: disable=broad-except
            group_members = []
            st.error(f"Could not load the matched transaction: {exc}")
        other_legs = [m for m in group_members if m["id"] != tx_id]
        if other_legs:
            for leg in other_legs:
                st.caption(f"Matched with: {leg['date']} · {leg['raw_description']} · ${leg['amount']:.2f}")
        else:
            st.caption(f"Auto-linked as a Transfer (group {tx['transfer_group_id']}).")
        col1, col2 = st.columns(2)
        if col1.button("Confirm", key=f"confirm_linked_{tx_id}"):
            confirm_transfer_match(tx_id)
            st.session_state["_review_action_success"] = f"Transaction {tx_id}: transfer match confirmed."
            st.rerun()
        if col2.button("Not a transfer", key=f"reject_linked_{tx_id}"):
            reject_transfer_match(tx_id)
            st.session_state["_review_action_success"] = f"Transaction {tx_id}: unlinked as not a transfer."
            st.rerun()
        return

    # Tier-2 Low: suggestion only, not yet linked — recomputed on demand (transfers/detection.py).
    try:
        suggestion = get_suggested_transfer_match(tx_id)
    except Exception as exc:  # pylint: disable=broad-except
        st.error(f"Could not load a suggested match: {exc}")
        return

    if suggestion is None:
        st.caption("No current candidate match.")
        if st.button("Dismiss", key=f"dismiss_{tx_id}"):
            reject_transfer_match(tx_id)
            st.session_state["_review_action_success"] = f"Transaction {tx_id}: dismissed."
            st.rerun()
        return

    st.caption(
        f"Suggested match: {suggestion['date']} · {suggestion['raw_description']} · ${suggestion['amount']:.2f}"
    )
    col1, col2 = st.columns(2)
    if col1.button("Confirm match", key=f"confirm_suggested_{tx_id}"):
        confirm_transfer_with_id(tx_id, suggestion["id"])
        st.session_state["_review_action_success"] = f"Transaction {tx_id}: linked as a Transfer."
        st.rerun()
    if col2.button("Not a transfer", key=f"reject_suggested_{tx_id}"):
        reject_transfer_match(tx_id)
        st.session_state["_review_action_success"] = f"Transaction {tx_id}: dismissed."
        st.rerun()


def _render_refund_ambiguity(tx: dict) -> None:
    tx_id = tx["id"]
    col1, col2 = st.columns(2)
    if col1.button("It's a refund", key=f"refund_yes_{tx_id}"):
        correct_transaction_is_refund(tx_id, True)
        st.session_state["_review_action_success"] = f"Transaction {tx_id}: marked as a refund."
        st.rerun()
    if col2.button("Not a refund", key=f"refund_no_{tx_id}"):
        correct_transaction_is_refund(tx_id, False)
        st.session_state["_review_action_success"] = f"Transaction {tx_id}: marked as not a refund."
        st.rerun()


def _render_low_confidence_category(tx: dict) -> None:
    tx_id = tx["id"]
    selected_category, selected_subcategory = render_category_correction_widget(
        category_key=f"needs_review_category_{tx_id}",
        subcategory_key=f"needs_review_subcategory_{tx_id}",
        last_seen_key=f"_needs_review_last_seen_category_{tx_id}",
        default_category=tx.get("category"),
        default_subcategory=tx.get("subcategory"),
    )

    if st.button("Save category", key=f"save_category_{tx_id}"):
        try:
            correct_transaction_category(tx_id, category=selected_category, subcategory=selected_subcategory)
            st.session_state["_review_action_success"] = f"Transaction {tx_id} updated to {selected_category}."
            st.rerun()
        except Exception as exc:  # pylint: disable=broad-except
            st.error(f"Could not save correction: {exc}")


try:
    items = get_transactions(needs_review=True)
except Exception as exc:  # pylint: disable=broad-except
    st.error(f"Could not load the review queue: {exc}")
    st.stop()

if not items:
    st.info("Nothing needs review right now.")
    st.stop()

present_reasons = sorted({t.get("needs_review_reason") for t in items if t.get("needs_review_reason")})
reason_options = [ALL_REASONS_LABEL] + [_reason_label(r) for r in present_reasons]
selected_reason_label = st.selectbox("Reason", reason_options, key="needs_review_reason_select")

if selected_reason_label == ALL_REASONS_LABEL:
    filtered = items
else:
    filtered = [t for t in items if _reason_label(t.get("needs_review_reason")) == selected_reason_label]

st.caption(f"{len(filtered)} item(s)")

for tx in filtered:
    reason = tx.get("needs_review_reason")
    with st.container(border=True):
        _row_header(tx)
        if reason == TRANSFER_MATCH:
            _render_transfer_match(tx)
        elif reason == REFUND_AMBIGUITY:
            _render_refund_ambiguity(tx)
        elif reason == LOW_CONFIDENCE_CATEGORY:
            _render_low_confidence_category(tx)
        else:
            # unrecognised_account (and any future backfill_flagged rows, J8): surfaced for
            # visibility per docs/design-logic-and-ux.md §3.2, but resolving an unrecognised
            # account needs account rename/merge tooling that doesn't exist yet — out of J5's
            # scope (no journey covers account management). A known, honest gap, not silently
            # hidden.
            st.caption("No action available yet for this reason — visibility only.")
