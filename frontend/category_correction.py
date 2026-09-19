from __future__ import annotations

from typing import Optional

import streamlit as st

from categorisation.taxonomy import CATEGORIES, TAXONOMY


def render_category_correction_widget(
    *,
    category_key: str,
    subcategory_key: str,
    last_seen_key: str,
    default_category: Optional[str] = None,
    default_subcategory: Optional[str] = None,
    category_label: str = "Category",
    subcategory_label: str = "Subcategory",
) -> tuple[str, Optional[str]]:
    """
    Category + subcategory selectboxes, sharing the reset-on-category-change guard used by both
    Category Drill-in and Needs-Review: a category change can leave the subcategory widget's
    persisted `session_state` value outside the new category's option list (e.g. switching to a
    category with fewer/no subcategories), so it must be explicitly reset rather than left stale.

    Callers control every session_state key so each page's existing key naming (and therefore its
    existing tests) is unaffected by sharing this widget.

    Returns the currently selected (category, subcategory-or-None).
    """
    if default_category is not None and category_key not in st.session_state:
        seeded_category = default_category if default_category in CATEGORIES else CATEGORIES[0]
        st.session_state[category_key] = seeded_category
        # Seed the subcategory and last-seen marker together with the category, on this same
        # first render — otherwise the reset-on-change guard below fires unconditionally on first
        # render (last_seen_key isn't set yet, so it never equals seeded_category) and silently
        # wipes a still-valid default subcategory back to "" before the user ever touches anything
        # (/code-review finding: this could drop an already-correct subcategory on save).
        if subcategory_key not in st.session_state:
            valid_subcategories = TAXONOMY[seeded_category]
            st.session_state[subcategory_key] = (
                default_subcategory if default_subcategory in valid_subcategories else ""
            )
        if last_seen_key not in st.session_state:
            st.session_state[last_seen_key] = seeded_category

    selected_category = st.selectbox(category_label, CATEGORIES, key=category_key)

    if st.session_state.get(last_seen_key) != selected_category:
        st.session_state[subcategory_key] = ""
        st.session_state[last_seen_key] = selected_category

    selected_subcategory = st.selectbox(
        subcategory_label, [""] + TAXONOMY[selected_category], key=subcategory_key
    )

    return selected_category, selected_subcategory or None
