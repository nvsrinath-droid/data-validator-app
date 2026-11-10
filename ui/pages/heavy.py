import streamlit as st

from core.sources import FilePair

from ..components import render_mapping_workflow
from ..inputs import local_paths_allowed, path_input, release_input, resolve_input


def render():
    st.markdown("**🟢 Active Engine:** Massive Data Files (DuckDB, streamed from disk)")
    st.markdown("Upload the files" + (", or give a file path on the server." if local_paths_allowed() else "."))

    uk = st.session_state.uploader_key
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📁 Source Data (System of Record)")
        upload_1 = st.file_uploader("Upload Source File", type=["csv", "xlsx", "xls"], key=f"hup1_{uk}")
        path_1 = path_input("OR: Local File Path 1 (if running locally)", f"hfile1_{uk}")
    with col2:
        st.subheader("📄 Target Data (To Compare)")
        upload_2 = st.file_uploader("Upload Target File", type=["csv", "xlsx", "xls"], key=f"hup2_{uk}")
        path_2 = path_input("OR: Local File Path 2 (if running locally)", f"hfile2_{uk}")

    for slot, upload in (("heavy1", upload_1), ("heavy2", upload_2)):
        if not upload:
            release_input(slot)                 # the file was removed from the uploader: delete its temp copy
    if not ((upload_1 or path_1) and (upload_2 or path_2)):
        return
    file_1 = resolve_input(upload_1, path_1, "heavy1")
    file_2 = resolve_input(upload_2, path_2, "heavy2")
    if not file_1 or not file_2:
        return

    render_mapping_workflow(FilePair(file_1, file_2), "heavy",
                            run_label="🚀 Run Massive File Comparison (Disk Streaming)",
                            spinner="Piping massive files to the DuckDB analytic engine...",
                            results_title="📊 Massive File Validation Results", file_slug="massive")
