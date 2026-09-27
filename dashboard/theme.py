"""Shared dark theme + page setup for every dashboard page."""

import streamlit as st

DEMO_BANNER_CSS = """
<style>
.demo-banner {
    background: #3a1f00;
    border: 1px solid #a15c00;
    color: #ffcc80;
    padding: 0.6rem 1rem;
    border-radius: 6px;
    font-size: 0.9rem;
    margin-bottom: 1rem;
}
.status-locked { color: #66bb6a; font-weight: 600; }
.status-experimental { color: #ffb74d; font-weight: 600; }
.status-progress { color: #4fc3f7; font-weight: 600; }
</style>
"""


def configure_page(title: str) -> None:
    st.set_page_config(
        page_title=f"Kunal Quant — {title}",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(DEMO_BANNER_CSS, unsafe_allow_html=True)


def demo_banner(scope: str = "This page") -> None:
    st.markdown(
        f'<div class="demo-banner">⚠️ DEMO DATA — {scope} is showing '
        "randomly generated placeholder numbers, not real market or "
        "account data. This banner is removed automatically once a page "
        "is wired to a real data source.</div>",
        unsafe_allow_html=True,
    )


def real_data_banner(source_note: str) -> None:
    st.markdown(
        f'<div class="demo-banner" style="background:#0d2b1a;border-color:#2e7d32;color:#a5d6a7;">'
        f"✅ REAL DATA — {source_note}</div>",
        unsafe_allow_html=True,
    )
