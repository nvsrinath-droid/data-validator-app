import streamlit as st

from connectors.file_connector import FileConnector
from connectors.sql_connector import SQLConnector
from core.db import redact
from core.sources import ConnectorPair

from ..components import render_mapping_workflow, render_sql_form


def _source_input(side: str, title: str, label: str):
    uk = st.session_state.uploader_key
    st.subheader(title)
    kind = st.radio(f"{label} Type", ["File Upload", "SQL Database"], horizontal=True, key=f"{side}_type_{uk}")
    if kind == "File Upload":
        return st.file_uploader(f"Upload {label}", type=["csv", "xlsx"], key=f"{side}_file_{uk}")
    return render_sql_form(f"{side}_{uk}")


def _connector(source):
    if isinstance(source, dict):
        return SQLConnector(source["url"], source["query"]), ("sql", repr(source["url"]), source["query"])
    return FileConnector(source), ("file", source.file_id)


def render():
    st.markdown("**🟢 Active Engine:** Standard Data Files (pandas, in memory)")

    col1, col2 = st.columns(2)
    with col1:
        source_1 = _source_input("src1", "📁 Source Data (System of Record)", "Source")
    with col2:
        source_2 = _source_input("src2", "📄 Target Data (To Compare)", "Target")

    if not (source_1 and source_2):
        return

    try:
        (conn1, sig1), (conn2, sig2) = _connector(source_1), _connector(source_2)
    except Exception as e:
        msg = str(e)
        for src in (source_1, source_2):
            if isinstance(src, dict):
                msg = redact(msg, src["url"])
        st.error(f"Error connecting to data source: {msg}")
        return

    render_mapping_workflow(ConnectorPair(conn1, conn2, signature=(sig1, sig2)), "std",
                            run_label="🚀 Run Full Data Comparison", spinner="Comparing all rows...",
                            results_title="📊 Validation Results")
