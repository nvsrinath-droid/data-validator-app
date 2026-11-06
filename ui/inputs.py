"""Input helpers shared by the file-based tiers."""
import os
import tempfile
from typing import Optional

import streamlit as st


def resolve_input(upload, path: str, prefix: str) -> Optional[str]:
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
