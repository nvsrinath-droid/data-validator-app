"""Input helpers shared by the file-based tiers."""
import os
import tempfile
from typing import Optional

import streamlit as st

ALLOWED_EXTENSIONS = (".csv", ".xlsx", ".xls")
LOCAL_PATHS_ENV = "TRUEALIGN_ALLOW_LOCAL_PATHS"


def local_paths_allowed() -> bool:
    """Server-side file paths are off unless the operator opts in: on a shared server a path box lets any user
    read any file the app can read."""
    return os.environ.get(LOCAL_PATHS_ENV) == "1"


def path_input(label: str, key: str, placeholder: str = "") -> str:
    """A server-side path box (a file, or a SQLite database), or "" (and a one-line hint) when local paths are not
    enabled."""
    if not local_paths_allowed():
        st.caption(f"Server file paths are disabled. To read files from this machine, start the app with "
                   f"{LOCAL_PATHS_ENV}=1.")
        return ""
    return st.text_input(label, key=key, placeholder=placeholder)


def resolve_input(upload, path: str, prefix: str) -> Optional[str]:
    """Uploaded file -> temp path (written once per upload), or a validated server-side path."""
    if upload:
        temp_path = os.path.join(tempfile.gettempdir(), f"truealign_{prefix}_{upload.file_id}_{os.path.basename(upload.name)}")
        if not os.path.exists(temp_path):
            with open(temp_path, "wb") as f:
                f.write(upload.getbuffer())
        return temp_path
    if path and local_paths_allowed():
        norm_path = os.path.normpath(path.strip('"\'‪‬ '))
        if not norm_path.lower().endswith(ALLOWED_EXTENSIONS):
            # Checked before the file is looked up, so the message does not reveal whether a path exists.
            st.error(f"❌ Only {', '.join(ALLOWED_EXTENSIONS)} files can be opened by path.")
            return None
        if os.path.isfile(norm_path):
            return norm_path
        st.error(f"❌ Server path not found: `{norm_path}`")
    return None
