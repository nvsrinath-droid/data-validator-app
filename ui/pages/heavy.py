import os
import tempfile
from typing import Optional

import streamlit as st

from core.sources import FilePair

from ..components import render_mapping_workflow


def _resolve_input(upload, path: str, prefix: str) -> Optional[str]:
    """Uploaded file -> temp path (written once per upload), or a validated server-side path."""
    if upload:
        temp_path = os.path.join(tempfile.gettempdir(), f"truealign_{prefix}_{upload.file_id}_{os.path.basename(upload.name)}")
        if not os.path.exists(temp_path):
            with open(temp_path, "wb") as f:
                f.write(upload.getbuffer())
        return temp_path
    if path:
        norm_path = os.path.normpath(path.strip('"\'‪‬ '))
        if os.path.isfile(norm_path):
            return norm_path
        st.error(f"❌ Server path not found: `{norm_path}`")
    return None


def render():
    st.markdown("**🟢 Active Engine:** Massive Data Files (DuckDB, streamed from disk)")
    st.markdown("Upload the files, or give a file path on the server if you are running the app locally.")

    uk = st.session_state.uploader_key
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📁 Source Data (System of Record)")
        upload_1 = st.file_uploader("Upload Source File", type=["csv", "xlsx", "xls"], key=f"hup1_{uk}")
        path_1 = st.text_input("OR: Local File Path 1 (if running locally)", key=f"hfile1_{uk}")
    with col2:
        st.subheader("📄 Target Data (To Compare)")
        upload_2 = st.file_uploader("Upload Target File", type=["csv", "xlsx", "xls"], key=f"hup2_{uk}")
        path_2 = st.text_input("OR: Local File Path 2 (if running locally)", key=f"hfile2_{uk}")

    if not ((upload_1 or path_1) and (upload_2 or path_2)):
        return
    file_1 = _resolve_input(upload_1, path_1, "heavy1")
    file_2 = _resolve_input(upload_2, path_2, "heavy2")
    if not file_1 or not file_2:
        return

    render_mapping_workflow(FilePair(file_1, file_2), "heavy",
                            run_label="🚀 Run Heavy File Comparison (Disk Streaming)",
                            spinner="Piping massive files to the DuckDB analytic engine...",
                            results_title="📊 Heavy Validation Results")
