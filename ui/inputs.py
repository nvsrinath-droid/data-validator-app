"""Input helpers shared by the file-based tiers."""
import os
import re
import shutil
import tempfile
import time
import unicodedata
import weakref
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


def is_network_path(cleaned: str) -> bool:
    r"""UNC and device paths (\\host\share, //host/share, \\?\...). Opening one makes Windows contact that host
    and send the account's credentials to it (NTLM), so a path box must never follow one, whatever the extension."""
    return cleaned.startswith(("\\\\", "//"))


STORE_DIR_PREFIX = "truealign_uploads_"
LEGACY_PREFIX = "truealign_"            # uploads used to be loose files named truealign_<tier>_<id>_<name>
STALE_AFTER_SECONDS = 24 * 3600
_SAFE = re.compile(r"[^A-Za-z0-9_-]")
_swept = False


def sweep_stale_uploads(older_than: float = STALE_AFTER_SECONDS, directory: Optional[str] = None) -> int:
    """Delete upload leftovers (from sessions that ended without cleaning up, or from older versions of the app)
    that nothing has touched for a day. A live session touches its folder on every rerun, so it is never old.
    Returns how many entries were removed."""
    root = directory or tempfile.gettempdir()
    cutoff = time.time() - older_than
    removed = 0
    try:
        entries = list(os.scandir(root))
    except OSError:
        return 0
    for entry in entries:
        if not entry.name.startswith(LEGACY_PREFIX):
            continue
        try:
            if entry.stat(follow_symlinks=False).st_mtime >= cutoff:
                continue
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path, ignore_errors=True)
            elif entry.is_file(follow_symlinks=False):
                os.remove(entry.path)
            else:
                continue
            removed += 1
        except OSError:
            pass                                        # in use or not ours to delete: leave it
    return removed


class UploadStore:
    """One session's uploaded files, kept in a private folder and deleted as soon as they are not needed.

    - The folder is created by tempfile.mkdtemp (owner-only), and each file with O_EXCL and mode 0600, so other
      accounts on the machine cannot read an upload (on Windows, Python 3.12+ limits the folder to the owner,
      SYSTEM and Administrators; the test suite checks it with icacls).
    - The name on disk is built from the slot and the upload's id plus its extension; the user's file name is
      never used for a path.
    - A slot (for example "quality" or "heavy1") holds one file: replacing or clearing the upload deletes it.
    - Everything goes when the store is garbage collected (the session ended) or the process exits.
    """

    def __init__(self, parent: Optional[str] = None):
        self.dir = tempfile.mkdtemp(prefix=STORE_DIR_PREFIX, dir=parent)
        self._slots = {}                                 # slot -> (upload id, path)
        self._finalizer = weakref.finalize(self, shutil.rmtree, self.dir, True)

    def put(self, slot: str, upload) -> str:
        upload_id = _SAFE.sub("_", str(upload.file_id))
        current = self._slots.get(slot)
        if current and current[0] == upload_id and os.path.isfile(current[1]):
            self._touch()
            return current[1]
        self.release(slot)
        extension = os.path.splitext(os.path.basename(upload.name))[1].lower()
        extension = extension if extension in ALLOWED_EXTENSIONS else ""
        path = os.path.join(self.dir, f"{_SAFE.sub('_', slot)}_{upload_id}{extension}")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        with os.fdopen(os.open(path, flags, 0o600), "wb") as f:
            f.write(upload.getbuffer())
        self._slots[slot] = (upload_id, path)
        self._touch()
        return path

    def release(self, slot: str) -> None:
        entry = self._slots.pop(slot, None)
        if entry:
            try:
                os.remove(entry[1])
            except FileNotFoundError:
                pass
            except OSError:
                pass            # still open (Windows) or already gone: the folder is removed with the session

    def release_all(self) -> None:
        for slot in list(self._slots):
            self.release(slot)

    def files(self) -> list:
        return sorted(os.listdir(self.dir)) if os.path.isdir(self.dir) else []

    def _touch(self) -> None:
        try:
            os.utime(self.dir)
        except OSError:
            pass


def upload_store() -> UploadStore:
    global _swept
    ss = st.session_state
    if "upload_store" not in ss:
        if not _swept:
            _swept = True
            sweep_stale_uploads()
        ss.upload_store = UploadStore()
    return ss.upload_store


def release_input(slot: str) -> None:
    """The upload in this slot was removed: delete its temp file now."""
    store = st.session_state.get("upload_store")
    if store is not None:
        store.release(slot)


def release_all_inputs() -> None:
    store = st.session_state.get("upload_store")
    if store is not None:
        store.release_all()


def resolve_input(upload, path: str, prefix: str) -> Optional[str]:
    """Uploaded file -> its private temp path (written once per upload), or a validated server-side path."""
    if upload:
        return upload_store().put(prefix, upload)
    release_input(prefix)
    if path and local_paths_allowed():
        cleaned = clean_path(path)
        if not cleaned:
            return None
        if is_network_path(cleaned):              # before normpath, which would turn // into \ on Windows
            st.error("❌ Network (UNC) paths are not allowed. Use a path on this machine, or upload the file.")
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
