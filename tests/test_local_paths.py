"""Typing a path into the Local File Path boxes (TRUEALIGN_ALLOW_LOCAL_PATHS=1), including Windows-style input."""
import unicodedata
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from ui.inputs import clean_path, local_paths_allowed

ROOT = Path(__file__).resolve().parents[1]
LRE, PDF, LRM, ZWSP, BOM, NBSP = "\u202a", "\u202c", "\u200e", "\u200b", "\ufeff", "\u00a0"
WIN = r"C:\Users\Ven Nanduri\data\a b.csv"          # a Windows path with spaces in it


@pytest.fixture
def spaced_csv(tmp_path):
    """A file under folders whose names contain spaces: <tmp>/Ven Nanduri/My Data/sales data.csv."""
    folder = tmp_path / "Ven Nanduri" / "My Data"
    folder.mkdir(parents=True)
    path = folder / "sales data.csv"
    pd.DataFrame({"ID": [1, 2, 3], "Amt": [10, 20, 30]}).to_csv(path, index=False)
    return str(path)


def open_tier(engine):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.session_state["is_guest"] = True
    at.query_params["auth"] = "guest"
    at.query_params["engine"] = engine
    return at.run()


# ---- the text cleaner ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    WIN,
    '"' + WIN + '"',                               # Explorer's "Copy as path"
    "'" + WIN + "'",
    "\u201c" + WIN + "\u201d",                     # curly quotes from a document or chat
    LRE + WIN,                                     # the file Properties dialog
    '"' + LRE + WIN + '"',
    WIN + PDF,
    LRM + ZWSP + BOM + WIN,
    "  \t" + WIN + NBSP + "\r\n",
])
def test_clean_path_keeps_the_path_and_drops_the_wrapping(raw):
    assert clean_path(raw) == WIN


def test_clean_path_only_touches_the_ends():
    assert clean_path("a b" + ZWSP + "c.csv") == "a b" + ZWSP + "c.csv"
    assert clean_path("it's here.csv") == "it's here.csv"
    assert clean_path('   ""  ') == ""
    assert all(unicodedata.category(c) == "Cf" for c in (LRE, PDF, LRM, ZWSP, BOM))


@pytest.mark.parametrize("value, allowed", [("1", True), ("1 ", True), (" 1", True), ("", False), ("0", False),
                                            ("true", False), ("11", False)])
def test_the_setting_tolerates_the_trailing_space_cmd_exe_leaves(monkeypatch, value, allowed):
    monkeypatch.setenv("TRUEALIGN_ALLOW_LOCAL_PATHS", value)     # cmd.exe: `set X=1 && streamlit run app.py` -> "1 "
    assert local_paths_allowed() is allowed


# ---- the quality tier ---------------------------------------------------------------------------

def test_quality_tier_opens_a_path_with_spaces(spaced_csv):
    at = open_tier("quality")
    at.text_input(key="qfile_0").set_value(spaced_csv).run()
    assert not at.exception, at.exception
    assert not at.error
    assert at.session_state["quality_profile"].row_count == 3


@pytest.mark.parametrize("wrap", [
    lambda p: '"' + p + '"', lambda p: LRE + p, lambda p: '"' + LRE + p + '"', lambda p: p + "  ",
    lambda p: "\u201c" + p + "\u201d", lambda p: LRM + p, lambda p: p.replace("\\", "/"),
])
def test_quality_tier_accepts_pasted_forms_of_a_spaced_path(spaced_csv, wrap):
    at = open_tier("quality")
    at.text_input(key="qfile_0").set_value(wrap(spaced_csv)).run()
    assert not at.error and at.session_state["quality_profile"].row_count == 3


def test_the_box_tells_the_user_to_press_enter():
    at = open_tier("quality")
    assert any("Press **Enter**" in c.value for c in at.caption)
    assert "Enter" in at.text_input(key="qfile_0").help


def test_error_messages_say_what_is_wrong(tmp_path, spaced_csv):
    at = open_tier("quality")
    folder_named_like_a_file = tmp_path / "dir.csv"
    folder_named_like_a_file.mkdir()
    cases = [(str(Path(spaced_csv).parent), "Only .csv"),                       # a folder: no extension
             (str(folder_named_like_a_file), "is a folder"),
             (str(tmp_path / "No Such Folder" / "x.csv"), "not found"),
             (str(tmp_path / "notes.txt"), "Only .csv")]
    for value, expected in cases:
        at.text_input(key="qfile_0").set_value(value).run()
        assert not at.exception, at.exception
        assert any(expected in e.value for e in at.error), (value, [e.value for e in at.error])
    at.text_input(key="qfile_0").set_value(spaced_csv).run()
    assert not at.error                                                          # and a good path clears them


# ---- the massive-files tier ---------------------------------------------------------------------

def test_heavy_tier_opens_two_paths_with_spaces(spaced_csv):
    at = open_tier("heavy")
    at.text_input(key="hfile1_0").set_value('"' + LRE + spaced_csv + '"')
    at.text_input(key="hfile2_0").set_value(spaced_csv).run()
    assert not at.exception, at.exception
    assert not at.error
    assert any(b.key == "heavy_manual" for b in at.button)       # the mapping step is reached


# ---- legacy .xls ----------------------------------------------------------------------------------

def test_requirements_include_xlrd_and_it_is_importable():
    assert any(line.split("#")[0].strip().lower().startswith("xlrd")
               for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines())
    import xlrd  # noqa: F401  (pandas needs it for .xls)


def test_an_xls_file_can_be_profiled_by_path():
    at = open_tier("quality")
    at.text_input(key="qfile_0").set_value(str(ROOT / "tests" / "data" / "tiny.xls")).run()
    assert not at.exception, at.exception
    assert not at.error
    profile = at.session_state["quality_profile"]
    assert profile.row_count == 3 and [c.name for c in profile.columns] == ["ID", "Amount"]
