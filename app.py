"""TrueAlign Data - Streamlit entry point. Run with: streamlit run app.py"""
import streamlit as st
from dotenv import load_dotenv

# Page config must be the first Streamlit call
st.set_page_config(page_title="TrueAlign Data", page_icon="🎯", layout="wide")
load_dotenv()

from ui.auth_view import render_header, require_login  # noqa: E402
from ui.landing import render_landing  # noqa: E402
from ui.pages import heavy, pushdown, standard  # noqa: E402
from ui.state import clear_workflow, init_state, sync_auth_with_url  # noqa: E402
from ui.styles import inject_premium_css  # noqa: E402

PAGES = {"standard": standard.render, "heavy": heavy.render, "pushdown": pushdown.render}

inject_premium_css()
init_state()
sync_auth_with_url()
render_header()
require_login()

# The engine lives in ?engine= so the browser Back button returns to the tier picker.
engine = st.query_params.get("engine")
if engine != st.session_state.get("execution_tier"):
    clear_workflow()  # a mapping made for one tier's inputs doesn't apply to another
    st.session_state.execution_tier = engine if engine in PAGES else None

if st.session_state.execution_tier is None:
    render_landing()
else:
    PAGES[st.session_state.execution_tier]()
