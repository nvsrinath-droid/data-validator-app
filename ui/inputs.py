"""Input helpers shared by the file-based tiers."""
import os
import tempfile
import unicodedata
from typing import Optional

import streamlit as st

ALLOWED_EXTENSIONS = (".csv", ".xlsx", ".xls")
LOCAL_PATHS_ENV = "TRUEALIGN_ALLOW_LOCAL_PATHS"


def local_paths_allowed() -> bool:
    """Server-side file paths are off unless the operator opts in: on a shared server a path box lets any user
    read any file the app can read."""
    # strip(): in cmd.exe, `set X=1 && streamlit run app.py` stores "1 " (the space before &&), which would
    # otherwise silently keep the boxes hidden.
    return os.environ.get(LOCAL_PATHS_ENV, "").strip() == "1"


def path_input(label: str, key: str, placeholder: str = "") -> str:
    """A server-side path box (a file, or a SQLite database), or "" (and a one-line hint) when local paths are not
    enabled."""
    if not local_paths_allowed():
        st.caption(f"Server file paths are disabled. To read files from this machine, start the app with "
                   f"{LOCAL_PATHS_ENV}=1.")
        return ""
    value = st.text_input(label, key=key, placeholder=placeholder,
                          help="Type or paste the full path, then press Enter (or click outside the box) to apply it.")
    # A Streamlit text box only sends its value on Enter or when it loses focus, so a path that was typed but not
    # confirmed looks exactly like no path at all.
    st.caption("Press **Enter** after typing or pasting the path.")
    return value


_QUOTES = {'"', "'", "\u201c", "\u201d", "\u2018", "\u2019", "`"}


def _strippable(ch: str) -> bool:
    # Whitespace, quotes ("Copy as path", curly quotes from chat apps and documents) and invisible format
    # characters: Windows' file Properties dialog prefixes a path with U+202A, other sources add U+200E, U+200B or
    # a BOM, and none of them show up in the box.
    return ch.isspace() or ch in _QUOTES or unicodedata.category(ch) == "Cf"


def clean_path(raw: str) -> str:
    """What the user meant by the text they typed or pasted: the same string without wrapping quotes, whitespace
    or invisible characters at either end. Spaces inside the path are kept (C:\\Users\\Ven Nanduri\\x.csv)."""
    start, end = 0, len(raw)
    while start < end and _strippable(raw[start]):
        start += 1
    while end > start and _strippable(raw[end - 1]):
        end -= 1
    return raw[start:end]


def resolve_input(upload, path: str, prefix: str) -> Optional[str]:
    """Uploaded file -> temp path (written once per upload), or a validated server-side path."""
    if upload:
        temp_path = os.path.join(tempfile.gettempdir(), f"truealign_{prefix}_{upload.file_id}_{os.path.basename(upload.name)}")
        if not os.path.exists(temp_path):
            with open(temp_path, "wb") as f:
                f.write(upload.getbuffer())
        return temp_path
    if path and local_paths_allowed():
        cleaned = clean_path(path)
        if not cleaned:
            return None
        norm_path = os.path.normpath(cleaned)
        if not norm_path.lower().endswith(ALLOWED_EXTENSIONS):
            # Checked before the file is looked up, so the message does not reveal whether a path exists.
            st.error(f"❌ Only {', '.join(ALLOWED_EXTENSIONS)} files can be opened by path.")
            return None
        if os.path.isdir(norm_path):
            st.error(f"❌ `{norm_path}` is a folder. Give the path of the file itself.")
        elif not os.path.isfile(norm_path):
            st.error(f"❌ Server path not found: `{norm_path}`. Check the spelling, and that the file is on the "
                     f"machine running the app.")
        elif not os.access(norm_path, os.R_OK):
            st.error(f"❌ `{norm_path}` exists but the app is not allowed to read it.")
        else:
            return norm_path
    return None
