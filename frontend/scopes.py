"""
The Day-to-day / Capital & financing / Everything switch shared by Overview and Portfolio, so the two
pages can't drift apart on labels, default or wording. The labels map to the API's `scope`.
"""

from __future__ import annotations

import streamlit as st

SCOPES = {"Day-to-day": "operating", "Capital & financing": "capital", "Everything": "all"}

_CAPTIONS = {
    "operating": (
        "Day-to-day only: property sales and purchases, share and super contributions, and loan "
        "drawdowns and paydowns are hidden. Choose Capital & financing or Everything to see them."
    ),
    "capital": "Capital & financing events only: property sales and purchases, contributions, loan "
               "drawdowns and paydowns.",
}


def choose_scope(key: str) -> str:
    """Render the switch (default Day-to-day) and return the API scope it stands for."""
    label = st.radio("Show", list(SCOPES), horizontal=True, key=key)
    scope = SCOPES[label]
    if scope in _CAPTIONS:
        st.caption(_CAPTIONS[scope])
    return scope
