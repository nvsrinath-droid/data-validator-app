"""Input helpers shared by the file-based tiers."""
import os
import re
import secrets
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
    # Windows treats / and \ alike, so /\host, \/host and //host all mean \\host. Spelled out with replace() instead
    # of os.path, so that the answer is the same on every OS.
    unified = cleaned.replace("/", "\\")
    return unified.startswith(("\\\\", "\\??\\"))


STORE_DIR_PREFIX = "truealign_uploads_"
LEGACY_PREFIX = "truealign_"            # uploads used to be loose files named truealign_<tier>_<id>_<name>
STALE_AFTER_SECONDS = 24 * 3600
_MARKER = ".truealign_store"
_SAFE = re.compile(r"[^A-Za-z0-9_-]")
_swept = False
# Paths (files, or whole session folders) that could not be deleted, usually because Windows still had them open.
# They are retried when the next file is released or written, when a new session starts, and by the sweep, so a
# failed delete is not forgotten until the one-day cleanup.
_pending: set = set()


def _delete(path: str) -> bool:
    """Delete a file or folder. A failure is recorded in _pending and returns False; "already gone" is success."""
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        _pending.add(path)
        return False
    _pending.discard(path)
    return True


def retry_pending_deletes() -> int:
    """Try again every delete that failed earlier. Returns how many were removed now."""
    return sum(1 for path in list(_pending) if _delete(path))


def sweep_stale_uploads(older_than: float = STALE_AFTER_SECONDS, directory: Optional[str] = None) -> int:
    """Delete upload leftovers that nothing has touched for a day. Only two kinds of entry are ever candidates:
    a loose file from older versions of the app (truealign_<tier>_<id>_<name>), and a session folder
    (truealign_uploads_*) that has sat idle. A live session's folder is touched on every rerun
    (keep_session_folder_fresh), so it is never idle; any other entry, including a folder or file that merely starts
    with "truealign_", is left alone. Returns how many entries were removed."""
    retry_pending_deletes()
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
    - Everything goes when the store is garbage collected (the session ended) or the process exits. A delete that
      fails (a file Windows still has open) is recorded and retried later, not forgotten.
    """

    def __init__(self, parent: Optional[str] = None):
        self._parent = parent
        self._slots = {}                                 # slot -> (upload id, path)
        self._token = secrets.token_hex(16)
        self.dir = self._make_dir()
        self._finalizer = weakref.finalize(self, _delete, self.dir)

    def _make_dir(self) -> str:
        """A new private folder holding a marker file with this store's secret token. The marker is how we later
        recognise the folder as the one we created (see _ensure_dir)."""
        new_dir = tempfile.mkdtemp(prefix=STORE_DIR_PREFIX, dir=self._parent)
        try:
            fd = os.open(os.path.join(new_dir, _MARKER), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                         0o600)
            with os.fdopen(fd, "w") as f:
                f.write(self._token)
        except BaseException:
            _delete(new_dir)
            raise
        return new_dir

    def _is_ours(self) -> bool:
        """True only for the folder this store created: a real directory (not a link) that holds our marker."""
        try:
            if os.path.islink(self.dir) or not os.path.isdir(self.dir):
                return False
            with open(os.path.join(self.dir, _MARKER), "r") as f:
                return f.read() == self._token
        except OSError:
            return False

    def _ensure_dir(self) -> None:
        """Something outside the app (another instance's sweep, Storage Sense, a temp cleaner) removed the folder
        while the session was open, or a different folder now sits under its name. Never adopt an existing folder:
        unless it carries our marker it is not ours, so make a new private one and forget the old name. Files from
        the old folder are gone, so their slots are forgotten and the next put writes them again."""
        if self._is_ours():
            return
        try:
            new_dir = self._make_dir()
        except OSError as e:
            raise UploadError(f"The upload folder could not be created ({e.strerror or type(e).__name__}).") from None
        self._finalizer.detach()
        self._slots.clear()
        self.dir = new_dir
        self._finalizer = weakref.finalize(self, _delete, self.dir)

    def put(self, slot: str, upload) -> str:
        upload_id = _SAFE.sub("_", str(upload.file_id))
        current = self._slots.get(slot)
        if current and current[0] == upload_id and os.path.isfile(current[1]):
            self.touch()
            return current[1]
        retry_pending_deletes()
        self._ensure_dir()
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
        except (OSError, MemoryError) as e:
            self._discard_partial(path)
            reason = "not enough memory" if isinstance(e, MemoryError) else (e.strerror or type(e).__name__)
            raise UploadError(f"The uploaded file could not be saved ({reason}).") from None
        except BaseException:
            self._discard_partial(path)         # anything else (a bug in getbuffer, Ctrl+C): clean up, then let it out
            raise

    @staticmethod
    def _discard_partial(path: str) -> None:
        try:
            os.remove(path)
        except OSError:
            pass

    def release(self, slot: str) -> None:
        entry = self._slots.pop(slot, None)
        if entry:
            _delete(entry[1])   # still open (Windows)? it is recorded and retried, and goes with the session folder

    def release_all(self) -> None:
        for slot in list(self._slots):
            self.release(slot)

    def files(self) -> list:
        return sorted(n for n in os.listdir(self.dir) if n != _MARKER) if os.path.isdir(self.dir) else []

    def touch(self) -> None:
        """Mark the folder as in use. Also brings it back if it was deleted under a live session."""
        try:
            self._ensure_dir()
            os.utime(self.dir)
        except (OSError, UploadError):
            pass


def upload_store() -> UploadStore:
    global _swept
    ss = st.session_state
    if "upload_store" not in ss:
        retry_pending_deletes()
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
        norm_path = os.path.normpath(cleaned)
        if is_network_path(cleaned) or is_network_path(norm_path):   # whichever spelling Windows would resolve
            st.error("❌ Network (UNC) paths are not allowed. Use a path on this machine, or upload the file.")
            return None
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
