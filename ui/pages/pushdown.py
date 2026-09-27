import streamlit as st

from core.db import redact
from core.engines.sql_pushdown import DEFAULT_SAMPLE_LIMIT
from core.sources import PushdownPair

from ..components import render_connection_fields, render_mapping_workflow


def render():
    st.markdown("**🟢 Active Engine:** Enterprise SQL Warehouses (pushdown)")

    st.subheader("🏢 Enterprise Database Connection")
    st.markdown("Both queries run inside this database. Only counts and a capped sample of exceptions are downloaded.")
    url = render_connection_fields("pd", label="SQL Dialect")

    st.markdown("---")
    c_q1, c_q2 = st.columns(2)
    with c_q1:
        st.subheader("📁 System of Record")
        q1 = st.text_area("SQL Query 1", placeholder="SELECT * FROM main_finance_table", key="pd_q1")
    with c_q2:
        st.subheader("📄 Target Data (To Compare)")
        q2 = st.text_area("SQL Query 2", placeholder="SELECT * FROM external_vendor_table", key="pd_q2")

    sample_limit = st.number_input("Max exception rows to download per category", min_value=10, max_value=100_000,
                                   value=DEFAULT_SAMPLE_LIMIT, step=100, key="pd_limit",
                                   help="Counts are always exact; this only caps the row-level detail.")

    if url is None or not q1 or not q2:
        return

    try:
        pair = PushdownPair(url, q1, q2, sample_limit=int(sample_limit))
    except Exception as e:
        st.error(f"Database connection failed: {redact(str(e), url)}")
        return

    render_mapping_workflow(pair, "pd", run_label="🚀 Push Validation Execution to Database",
                            spinner="Pushing the comparison down to the database...",
                            results_title="📊 Remote Database Execution Results")
