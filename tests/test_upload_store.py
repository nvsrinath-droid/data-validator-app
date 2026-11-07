"""Uploaded files: private temp folder, restrictive permissions, deleted when no longer needed."""
import gc
import os
import stat
import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import ui.inputs as inputs
from ui.inputs import UploadError, UploadStore, sweep_stale_uploads

ROOT = Path(__file__).resolve().parents[1]


class FakeUpload:
    """The bits of Streamlit's UploadedFile that the store uses."""

    def __init__(self, name="data.csv", content=b"a,b\n1,2\n", file_id="abc123"):
        self.name, self.file_id, self._content = name, file_id, content

    def getbuffer(self):
        return memoryview(self._content)


@pytest.fixture
def store(tmp_path):
    s = UploadStore(parent=str(tmp_path))
    yield s
    s._finalizer()


def test_put_writes_the_content_to_a_private_folder_and_never_uses_the_users_file_name(store, tmp_path):
    path = store.put("quality", FakeUpload(name="..\\..\\evil name.CSV", content=b"x,y\n1,2\n"))
    assert Path(path).read_bytes() == b"x,y\n1,2\n"
    assert Path(path).parent == Path(store.dir) and Path(store.dir).parent == tmp_path
    assert Path(path).name == "quality_abc123.csv"                  # slot + id + extension only
    assert "evil" not in path


def test_an_unknown_extension_is_not_kept(store):
    assert Path(store.put("q", FakeUpload(name="notes.exe"))).suffix == ""


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits (the Windows ACL is checked by the icacls test below)")
def test_files_and_folder_are_owner_only(store):
    path = store.put("quality", FakeUpload())
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(store.dir).st_mode) == 0o700


def test_the_same_upload_is_written_once(store):
    first = store.put("quality", FakeUpload())
    mtime = os.stat(first).st_mtime_ns
    assert store.put("quality", FakeUpload()) == first
    assert os.stat(first).st_mtime_ns == mtime


def test_replacing_an_upload_deletes_the_old_file(store):
    old = store.put("quality", FakeUpload(file_id="one"))
    new = store.put("quality", FakeUpload(file_id="two", content=b"c\n9\n"))
    assert not os.path.exists(old) and Path(new).read_bytes() == b"c\n9\n"
    assert store.files() == ["quality_two.csv"]


def test_slots_are_independent_and_release_removes_only_its_own(store):
    store.put("heavy1", FakeUpload(file_id="a"))
    store.put("heavy2", FakeUpload(file_id="b"))
    store.release("heavy1")
    assert store.files() == ["heavy2_b.csv"]
    store.release("heavy1")                                         # releasing twice is harmless
    store.release_all()
    assert store.files() == []


def test_a_file_that_vanished_is_written_again(store):
    path = store.put("quality", FakeUpload())
    os.remove(path)                                                 # e.g. removed by the stale-file sweep
    assert Path(store.put("quality", FakeUpload())).read_bytes() == b"a,b\n1,2\n"


def test_everything_is_deleted_when_the_session_object_goes_away(tmp_path):
    s = UploadStore(parent=str(tmp_path))
    s.put("quality", FakeUpload())
    folder = s.dir
    assert os.path.isdir(folder)
    del s
    gc.collect()
    assert not os.path.exists(folder)


def test_an_open_file_that_cannot_be_deleted_does_not_raise(store, monkeypatch):
    store.put("quality", FakeUpload())
    monkeypatch.setattr(os, "remove", lambda p: (_ for _ in ()).throw(PermissionError("in use")))
    store.release("quality")                                        # Windows: file still open elsewhere


class FailingUpload(FakeUpload):
    def getbuffer(self):
        raise OSError(28, "No space left on device")


def test_a_failed_write_removes_the_partial_file_and_raises_a_clean_error(store):
    with pytest.raises(UploadError) as err:
        store.put("quality", FailingUpload())
    assert store.files() == [] and store._slots == {}
    assert "No space left" in str(err.value) and store.dir not in str(err.value) and "quality_" not in str(err.value)
    assert Path(store.put("quality", FakeUpload())).is_file()       # and the slot is usable afterwards


def test_a_failure_while_filling_leaves_no_half_written_file(store, monkeypatch):
    real_fdopen = os.fdopen

    def writes_then_dies(fd, mode):
        f = real_fdopen(fd, mode)
        f.write = lambda data: (_ for _ in ()).throw(OSError(28, "No space left on device"))
        return f
    monkeypatch.setattr(os, "fdopen", writes_then_dies)
    with pytest.raises(UploadError):
        store.put("quality", FakeUpload())
    assert store.files() == []


def test_an_untracked_file_in_the_way_is_replaced_not_fatal(store):
    leftover = Path(store.dir) / "quality_abc123.csv"
    leftover.write_bytes(b"old,stale")                              # same name, but no slot knows about it
    assert Path(store.put("quality", FakeUpload())).read_bytes() == b"a,b\n1,2\n"
    assert store.files() == ["quality_abc123.csv"]


def test_resolve_input_shows_a_message_instead_of_crashing_when_saving_fails(monkeypatch, tmp_path):
    errors = []
    monkeypatch.setattr(inputs.st, "error", errors.append)
    monkeypatch.setattr(inputs, "upload_store", lambda: store)
    store = UploadStore(parent=str(tmp_path))
    assert inputs.resolve_input(FailingUpload(), "", "quality") is None
    assert len(errors) == 1 and "could not be saved" in errors[0] and str(tmp_path) not in errors[0]
    store._finalizer()


# ---- deletes that failed are remembered and retried ----------------------------------------------

@pytest.fixture
def pending(monkeypatch):
    fresh = set()
    monkeypatch.setattr(inputs, "_pending", fresh)
    return fresh


def test_a_file_that_could_not_be_deleted_is_recorded_and_retried_by_the_next_sweep(store, tmp_path, monkeypatch, pending):
    path = store.put("quality", FakeUpload())
    real_remove = os.remove
    monkeypatch.setattr(os, "remove", lambda p: (_ for _ in ()).throw(PermissionError("in use")))
    store.release("quality")
    assert pending == {path} and os.path.exists(path)
    monkeypatch.setattr(os, "remove", real_remove)                  # the other program closed the file
    sweep_stale_uploads(directory=str(tmp_path))
    assert not os.path.exists(path) and pending == set()


def test_pending_deletes_are_also_retried_on_the_next_put(store, monkeypatch, pending):
    first = store.put("quality", FakeUpload(file_id="one"))
    real_remove = os.remove
    monkeypatch.setattr(os, "remove", lambda p: (_ for _ in ()).throw(PermissionError("in use")))
    store.release("quality")
    monkeypatch.setattr(os, "remove", real_remove)
    store.put("quality", FakeUpload(file_id="two"))
    assert not os.path.exists(first) and pending == set()


def test_a_session_folder_that_could_not_be_removed_at_session_end_is_retried(tmp_path, monkeypatch, pending):
    s = UploadStore(parent=str(tmp_path))
    s.put("quality", FakeUpload())
    folder = s.dir
    real_rmtree = inputs.shutil.rmtree
    monkeypatch.setattr(inputs.shutil, "rmtree", lambda p, *a, **k: (_ for _ in ()).throw(PermissionError("in use")))
    del s
    gc.collect()
    assert os.path.isdir(folder) and pending == {folder}            # kept on record, not silently abandoned
    monkeypatch.setattr(inputs.shutil, "rmtree", real_rmtree)
    sweep_stale_uploads(directory=str(tmp_path))                    # even though the folder is far from a day old
    assert not os.path.exists(folder) and pending == set()


def test_a_pending_path_that_is_already_gone_is_just_forgotten(tmp_path, pending):
    pending.add(str(tmp_path / "vanished.csv"))
    inputs.retry_pending_deletes()
    assert pending == set()


# ---- sweeping leftovers --------------------------------------------------------------------------

def test_sweep_removes_only_old_truealign_leftovers(tmp_path):
    old_time = time.time() - 3 * 24 * 3600
    legacy_old = tmp_path / "truealign_heavy1_xyz_data.csv"        # the old flat-file naming
    legacy_old.write_text("x")
    old_dir = tmp_path / "truealign_uploads_dead"
    old_dir.mkdir()
    (old_dir / "quality_1.csv").write_text("x")
    for p in (legacy_old, old_dir):
        os.utime(p, (old_time, old_time))
    young_file = tmp_path / "truealign_quality_young.csv"
    young_file.write_text("x")
    young_dir = tmp_path / "truealign_uploads_live"
    young_dir.mkdir()
    unrelated_old = tmp_path / "somebody_elses.csv"
    unrelated_old.write_text("x")
    os.utime(unrelated_old, (old_time, old_time))

    assert sweep_stale_uploads(directory=str(tmp_path)) == 2
    assert not legacy_old.exists() and not old_dir.exists()
    assert young_file.exists() and young_dir.exists() and unrelated_old.exists()


def test_a_live_session_keeps_its_folder_fresh(store):
    old_time = time.time() - 3 * 24 * 3600
    os.utime(store.dir, (old_time, old_time))
    store.put("quality", FakeUpload())                              # every rerun with an upload touches the folder
    assert sweep_stale_uploads(directory=str(Path(store.dir).parent)) == 0
    assert os.path.isdir(store.dir)


def test_sweep_never_touches_a_look_alike_folder_or_a_session_folder_that_is_a_file(tmp_path):
    old = time.time() - 3 * 24 * 3600
    lookalike_dir = tmp_path / "truealign_exports"                  # someone's own folder, merely similarly named
    lookalike_dir.mkdir()
    (lookalike_dir / "keep.csv").write_text("x")
    legacy_named_dir = tmp_path / "truealign_quality_abc_data.csv"  # a directory wearing a legacy file name
    legacy_named_dir.mkdir()
    file_named_like_a_session = tmp_path / "truealign_uploads_notes.txt"
    file_named_like_a_session.write_text("x")
    for p in (lookalike_dir, legacy_named_dir, file_named_like_a_session):
        os.utime(p, (old, old))
    assert sweep_stale_uploads(directory=str(tmp_path)) == 0
    assert lookalike_dir.exists() and legacy_named_dir.exists() and file_named_like_a_session.exists()
    assert (lookalike_dir / "keep.csv").exists()


def test_every_rerun_touches_the_session_folder_even_with_no_upload_activity(tmp_path):
    store = UploadStore(parent=str(tmp_path))
    store.put("quality", FakeUpload())
    old = time.time() - 3 * 24 * 3600
    os.utime(store.dir, (old, old))
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.session_state["is_guest"] = True
    at.session_state["upload_store"] = store
    at.query_params["auth"] = "guest"
    at.run()                                                        # the landing page: no uploader involved
    assert not at.exception, at.exception
    assert os.stat(store.dir).st_mtime > time.time() - 60
    assert sweep_stale_uploads(directory=str(tmp_path)) == 0
    store._finalizer()


# ---- wiring into the app --------------------------------------------------------------------------

def test_resolve_input_uses_the_session_store_and_release_input_clears_it(monkeypatch, tmp_path):
    monkeypatch.setattr(inputs.tempfile, "tempdir", str(tmp_path))
    session = {}

    class State(dict):
        __getattr__ = dict.get

        def __setattr__(self, k, v):
            self[k] = v
    monkeypatch.setattr(inputs.st, "session_state", State(session))
    monkeypatch.setattr(inputs, "_swept", True)
    path = inputs.resolve_input(FakeUpload(), "", "quality")
    store = inputs.st.session_state["upload_store"]
    assert Path(path).parent == Path(store.dir) and os.path.isfile(path)
    inputs.release_input("quality")
    assert not os.path.exists(path)
    inputs.resolve_input(FakeUpload(), "", "quality")
    inputs.resolve_input(None, "", "quality")                       # uploader emptied, no path typed
    assert store.files() == []
    store._finalizer()


def test_switching_tier_deletes_uploaded_files(tmp_path):
    store = UploadStore(parent=str(tmp_path))
    path = store.put("quality", FakeUpload())
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.session_state["is_guest"] = True
    at.session_state["upload_store"] = store
    at.query_params["auth"] = "guest"
    at.query_params["engine"] = "quality"          # execution_tier is None, so app.py calls clear_workflow()
    at.run()
    assert not at.exception, at.exception
    assert not os.path.exists(path)
    store._finalizer()


@pytest.mark.skipif(os.name != "nt", reason="icacls is Windows only")
def test_on_windows_only_the_owner_system_and_administrators_have_access(store):
    import subprocess
    path = store.put("quality", FakeUpload())
    for target in (store.dir, path):
        acl = subprocess.run(["icacls", target], capture_output=True, text=True).stdout
        assert "OWNER RIGHTS" in acl
        for broad in ("Everyone", r"BUILTIN\Users", "Authenticated Users", r"NT AUTHORITY\INTERACTIVE"):
            assert broad not in acl, acl
