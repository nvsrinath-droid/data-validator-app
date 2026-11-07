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
    """Delete upload leftovers that nothing has touched for a day. Only two kinds of entry are ever candidates:
    a loose file from older versions of the app (truealign_<tier>_<id>_<name>), and a session folder
    (truealign_uploads_*) that has sat idle. A live session's folder is touched on every rerun
    (keep_session_folder_fresh), so it is never idle; any other entry, including a folder or file that merely starts
    with "truealign_", is left alone. Returns how many entries were removed."""
    root = directory or tempfile.gettempdir()
    cutoff = time.time() - older_than
    removed = 0
    try:
        entries = list(os.scandir(root))
    except OSError:
        return 0
    for entry in entries:
        is_session_folder = entry.name.startswith(STORE_DIR_PREFIX)
        is_legacy_name = entry.name.startswith(LEGACY_PREFIX) and not is_session_folder
        try:
            if is_session_folder:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            elif not (is_legacy_name and entry.is_file(follow_symlinks=False)):
                continue
            if entry.stat(follow_symlinks=False).st_mtime >= cutoff:
                continue
            if is_session_folder:
                shutil.rmtree(entry.path)
            else:
                os.remove(entry.path)
            removed += 1
        except OSError:
            pass                                        # in use or not ours to delete: leave it
    return removed


class UploadError(Exception):
    """An upload could not be written to the session folder. The message is safe to show: it names no path."""


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
            self.touch()
            return current[1]
        self.release(slot)
        extension = os.path.splitext(os.path.basename(upload.name))[1].lower()
        extension = extension if extension in ALLOWED_EXTENSIONS else ""
        path = os.path.join(self.dir, f"{_SAFE.sub('_', slot)}_{upload_id}{extension}")
        self._write(path, upload)
        self._slots[slot] = (upload_id, path)
        self.touch()
        return path

    def _write(self, path: str, upload) -> None:
        """Create `path` (owner-only, never overwriting) and fill it. If anything fails the partial file is removed
        and an UploadError, which does not name the path, is raised."""
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        try:
            try:
                fd = os.open(path, flags, 0o600)
            except FileExistsError:
                # Not tracked by any slot, so a leftover of this session's own folder (a crash between the write and
                # the bookkeeping, or a failed delete): replace it rather than fail.
                os.remove(path)
                fd = os.open(path, flags, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(upload.getbuffer())
        except OSError as e:
            try:
                os.remove(path)
            except OSError:
                pass
            raise UploadError(f"The uploaded file could not be saved ({e.strerror or type(e).__name__}).") from None

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

    def touch(self) -> None:
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


def keep_session_folder_fresh() -> None:
    """Called on every rerun, so the folder of a session that is still open is never mistaken for an idle one by
    another session's sweep (a folder's modification time only changes when files are added or removed)."""
    store = st.session_state.get("upload_store")
    if store is not None:
        store.touch()


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
        try:
            return upload_store().put(prefix, upload)
        except UploadError as e:
            st.error(f"❌ {e}")
            return None
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
            st.error("❌ That path is a folder. Give the path of the file itself.")
        elif not os.path.isfile(norm_path):
            st.error("❌ Server path not found. Check the spelling, and that the file is on the machine running "
                     "the app.")
        elif not os.access(norm_path, os.R_OK):
            st.error("❌ That file exists but the app is not allowed to read it.")
        else:
            return norm_path
    return None
