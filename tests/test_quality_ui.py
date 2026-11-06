"""The Data Quality tier: the checks grid, the page end to end (stubbed AI agent), and the privacy guard."""
import ast
from pathlib import Path

import pandas as pd
import pytest

from core.quality.engine import QualityEngine
from core.quality.profile import TableProfile
from core.quality.specs import Distinct, NullRate, Outliers, QualityResult
from ui.quality_grid import REF_MESSAGE, empty_frame, frame_to_specs, specs_to_frame

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = str(ROOT / "samples" / "inventory_system.csv")
COLUMNS = list(pd.read_csv(INVENTORY, nrows=1).columns)
FIRST = COLUMNS[0]


# ---- grid <-> specs ----------------------------------------------------------------------------

def test_grid_round_trips_specs():
    checks = [NullRate(column="a", max_pct=5, severity="warn"), Distinct(column="b", unique=True),
              Outliers(column="c", method="zscore", k=2.5, max_count=3)]
    specs, errors = frame_to_specs(specs_to_frame(checks), ["a", "b", "c"])
    assert errors == []
    assert specs == checks


def test_grid_rejects_ref_integrity_with_a_pointer_to_the_cli():
    frame = pd.DataFrame([{"type": "ref_integrity", "column": "a"}])
    specs, errors = frame_to_specs(frame, ["a"])
    assert specs == [] and errors == [f"Row 1: {REF_MESSAGE}"]
    assert "--ref" in errors[0] and "command line" in errors[0]


def test_grid_reports_each_bad_row_and_keeps_the_good_ones():
    frame = pd.DataFrame([
        {"type": "null_rate", "column": "a", "max_pct": 5},
        {"type": "null_rate", "column": "nope"},
        {"type": "null_rate", "column": "a", "max_pct": 500},
        {"type": "freshness", "column": "a", "max_age": "soon"},
        {"column": "a"},
    ])
    specs, errors = frame_to_specs(frame, ["a"])
    assert [s.type for s in specs] == ["null_rate"]
    assert len(errors) == 4 and all(e.startswith("Row ") for e in errors)


def test_grid_ignores_blank_rows():
    frame = pd.concat([empty_frame(), pd.DataFrame([{"unique": False}])], ignore_index=True)
    assert frame_to_specs(frame, ["a"]) == ([], [])


def test_grid_rejects_contradictory_and_extreme_values_and_never_raises():
    frame = pd.DataFrame([
        {"type": "distinct", "column": "a", "min_distinct": 5.0, "max_distinct": 1.0},
        {"type": "distinct", "column": "a", "min_distinct": 1e300},
        {"type": "outliers", "column": "a", "max_count": 1e13},
        {"type": ["x"], "column": "a"},
        {"type": "null_rate", "column": ["a"]},
        {"type": "distinct", "column": "a", "min_distinct": 1.0, "max_distinct": 5.0},
    ])
    specs, errors = frame_to_specs(frame, ["a"])
    assert [(s.min_distinct, s.max_distinct) for s in specs] == [(1, 5)]
    assert len(errors) == 5
    assert "greater than max_distinct" in errors[0] and "too large" in errors[1] and "too large" in errors[2]
    assert all(len(e) < 200 for e in errors)


def test_non_blank_rows_keeps_error_rows_and_drops_blank_ones():
    from ui.quality_grid import non_blank_rows
    frame = pd.DataFrame([{"type": "ref_integrity", "column": "a"}, {"column": None}, {"unique": False}])
    assert list(non_blank_rows(frame)["type"]) == ["ref_integrity"]


# ---- the page ----------------------------------------------------------------------------------

class FakeAgent:
    """Stands in for AIAgent. Records exactly what the page hands the two summary-only entry points."""
    calls = []

    def suggest_checks(self, profile, references=None, include_extremes=False, hide_column_names=False):
        FakeAgent.calls.append(("suggest", profile, include_extremes, hide_column_names))
        return [NullRate(column=FIRST, max_pct=1)], ["Dropped something."]

    def explain_results(self, result, include_extremes=False, hide_column_names=False):
        FakeAgent.calls.append(("explain", result, include_extremes, hide_column_names))
        return "Everything looks fine."

    def _call_llm(self, *a, **k):
        raise AssertionError("the page must not build prompts itself")


def _app(agent=None, monkeypatch=None):
    from streamlit.testing.v1 import AppTest
    if monkeypatch is not None:
        import ui.pages.quality as page
        monkeypatch.setattr(page, "model_picker", lambda key: agent)
    FakeAgent.calls = []
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.session_state["is_guest"] = True
    at.query_params["auth"] = "guest"
    at.query_params["engine"] = "quality"
    return at.run()


def _load(at, checks=None):
    at.text_input(key="qfile_0").set_value(INVENTORY).run()
    if checks is not None:
        at.session_state["quality_checks"] = specs_to_frame(checks)
        at.session_state["config_version"] += 1
        at.run()
    return at


def test_landing_page_has_four_cards():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.session_state["is_guest"] = True
    at.query_params["auth"] = "guest"
    at.run()
    assert not at.exception
    labels = [b.label for b in at.button]
    assert len([x for x in labels if x.startswith("Launch")]) == 4
    assert any("Launch Data Quality" in x for x in labels)


def test_quality_tier_renders_without_a_file():
    at = _app()
    assert not at.exception, at.exception
    assert not [b for b in at.button if b.key == "quality_run"]


def test_profile_grid_run_and_results():
    at = _load(_app(), [NullRate(column=FIRST, max_pct=100), Outliers(column=FIRST, method="zscore")])
    assert not at.exception, at.exception
    assert len(at.dataframe) >= 2                       # profile + checks grid
    at.button(key="quality_run").click().run()
    assert not at.exception, at.exception
    assert not at.error
    result = at.session_state["quality_result"]
    assert isinstance(result, QualityResult) and len(result.results) == 2
    assert [m.label for m in at.metric][0] == "Rows"
    labels = {d.proto.label for d in at.get("download_button")}
    assert {"⬇️ Report (JSON)", "⬇️ Results (CSV)", "⬇️ Checks (JSON)"} <= labels


def test_privacy_checkboxes_default_off_and_no_ai_buttons_without_a_key():
    at = _load(_app())
    assert [c.value for c in at.checkbox if c.key in ("quality_hide_names", "quality_include_extremes")] == [False, False]
    assert not [b for b in at.button if b.key in ("quality_suggest", "quality_explain")]


def test_suggest_loads_the_grid_and_never_runs(monkeypatch):
    at = _load(_app(FakeAgent(), monkeypatch))
    at.checkbox(key="quality_hide_names").check().run()
    at.button(key="quality_suggest").click().run()
    assert not at.exception, at.exception
    kind, profile, extremes, hide = FakeAgent.calls[-1]
    assert kind == "suggest" and isinstance(profile, TableProfile)
    assert (extremes, hide) == (False, True)
    assert "quality_result" not in at.session_state     # reviewed first, never run automatically
    grid = at.session_state["quality_checks"]
    assert list(grid["type"]) == ["null_rate"] and list(grid["column"]) == [FIRST]
    assert any("Dropped something." in i.value for i in at.info)
    assert "Only column statistics are sent, no rows." in [c.value for c in at.caption]


def test_suggest_keeps_rows_that_have_errors(monkeypatch):
    at = _load(_app(FakeAgent(), monkeypatch))
    at.session_state["quality_checks"] = pd.concat(
        [pd.DataFrame([{"type": "ref_integrity", "column": FIRST}]), empty_frame()], ignore_index=True)
    at.session_state["config_version"] += 1
    at.run()
    assert any("--ref" in e.value for e in at.error)
    at.button(key="quality_suggest").click().run()
    grid = at.session_state["quality_checks"]
    assert list(grid["type"]) == ["ref_integrity", "null_rate"]     # the bad row survived, suggestion appended


def test_changing_the_file_clears_notes_and_explanation(monkeypatch, tmp_path):
    other = tmp_path / "other.csv"
    other.write_text("x,y\n1,2\n")
    at = _load(_app(FakeAgent(), monkeypatch), [NullRate(column=FIRST, max_pct=100)])
    at.button(key="quality_run").click().run()
    at.button(key="quality_explain").click().run()
    at.session_state["quality_notes"] = ["Dropped something about the old file."]
    at.run()
    assert at.info and at.session_state["quality_explanation"]
    at.text_input(key="qfile_0").set_value(str(other)).run()
    assert not at.exception, at.exception
    for key in ("quality_notes", "quality_explanation", "quality_result"):
        assert key not in at.session_state
    assert not at.info


def test_profile_refreshes_when_the_file_changes_in_place(tmp_path):
    from streamlit.testing.v1 import AppTest
    f = tmp_path / "data.csv"
    f.write_text("a\n1\n")
    at = _app()
    at.text_input(key="qfile_0").set_value(str(f)).run()
    assert [c.name for c in at.session_state["quality_profile"].columns] == ["a"]
    f.write_text("a,b\n1,2\n3,4\n")
    at.run()
    prof = at.session_state["quality_profile"]
    assert [c.name for c in prof.columns] == ["a", "b"] and prof.row_count == 2


def test_explain_gets_the_result_object_and_the_flags(monkeypatch):
    at = _load(_app(FakeAgent(), monkeypatch), [NullRate(column=FIRST, max_pct=100)])
    at.button(key="quality_run").click().run()
    at.checkbox(key="quality_include_extremes").check().run()
    at.button(key="quality_explain").click().run()
    assert not at.exception, at.exception
    kind, result, extremes, hide = FakeAgent.calls[-1]
    assert kind == "explain" and isinstance(result, QualityResult)
    assert (extremes, hide) == (True, False)
    assert any("Everything looks fine." in t.value for t in at.text)


# ---- local file paths (review #1) and no-AI-key isolation (review #5) ------------------------------

@pytest.mark.parametrize("engine, key", [("quality", "qfile_0"), ("heavy", "hfile1_0")])
def test_path_boxes_are_hidden_unless_enabled(monkeypatch, engine, key):
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv("TRUEALIGN_ALLOW_LOCAL_PATHS")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.session_state["is_guest"] = True
    at.query_params["auth"] = "guest"
    at.query_params["engine"] = engine
    at.run()
    assert not at.exception, at.exception
    assert key not in [t.key for t in at.text_input]
    assert any("TRUEALIGN_ALLOW_LOCAL_PATHS=1" in c.value for c in at.caption)


@pytest.mark.parametrize("engine, key", [("pushdown", "sqlite_pd")])
def test_sqlite_database_path_box_is_hidden_unless_enabled(monkeypatch, engine, key):
    from streamlit.testing.v1 import AppTest

    def open_sqlite():
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
        at.session_state["is_guest"] = True
        at.query_params["auth"] = "guest"
        at.query_params["engine"] = engine
        at.run()
        at.selectbox(key="db_type_pd").select("SQLite (Local)").run()
        assert not at.exception, at.exception
        return at

    assert key in [t.key for t in open_sqlite().text_input]          # enabled (the fixture's default)
    monkeypatch.delenv("TRUEALIGN_ALLOW_LOCAL_PATHS")
    at = open_sqlite()
    assert key not in [t.key for t in at.text_input]
    assert any("TRUEALIGN_ALLOW_LOCAL_PATHS=1" in c.value for c in at.caption)


def test_sqlite_database_path_box_is_hidden_on_the_standard_tier_too(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv("TRUEALIGN_ALLOW_LOCAL_PATHS")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.session_state["is_guest"] = True
    at.query_params["auth"] = "guest"
    at.query_params["engine"] = "standard"
    at.run()
    at.radio(key="src1_type_0").set_value("SQL Database").run()
    at.selectbox(key="db_type_src1_0").select("SQLite (Local)").run()
    assert not at.exception, at.exception
    assert "sqlite_src1_0" not in [t.key for t in at.text_input]


def test_path_is_ignored_when_not_enabled(monkeypatch):
    from ui.inputs import resolve_input
    monkeypatch.delenv("TRUEALIGN_ALLOW_LOCAL_PATHS")
    assert resolve_input(None, INVENTORY, "t") is None


def test_enabled_paths_must_be_csv_or_excel(tmp_path):
    secret = tmp_path / "server.env"
    secret.write_text("OPENAI_API_KEY=sk-secret")
    at = _app()
    at.text_input(key="qfile_0").set_value(str(secret)).run()
    assert not at.exception, at.exception
    assert any("Only .csv, .xlsx, .xls" in e.value for e in at.error)
    assert "quality_profile" not in at.session_state
    # a missing file with a good extension still gets the ordinary message, and exposes nothing about the bad one
    at.text_input(key="qfile_0").set_value(str(tmp_path / "missing.csv")).run()
    assert any("not found" in e.value for e in at.error)


def test_tests_run_without_ai_keys_even_if_the_shell_has_one(monkeypatch):
    # the autouse fixture blanks every provider key, so this must hold regardless of the developer's shell
    at = _load(_app())
    assert not [b for b in at.button if b.key in ("quality_suggest", "quality_explain")]


# ---- header warning (#2), CSV formulas (#8), plain-text explanation (#9) ---------------------------

def test_header_warning_is_shown_with_the_ai_buttons_until_names_are_hidden(monkeypatch):
    from ui.pages.quality import HEADER_WARNING
    at = _load(_app(FakeAgent(), monkeypatch))
    assert any("first row is used as the column names" in w.value and "Hide column names" in w.value
               for w in at.warning)
    at.checkbox(key="quality_hide_names").check().run()
    assert not any(w.value == HEADER_WARNING for w in at.warning)


def test_csv_cells_that_look_like_formulas_are_neutralised():
    from core.quality.report import csv_safe, results_csv
    tab, cr = chr(9), chr(13)
    for text in ["=HYPERLINK(1)", "+1", "-2+3", "@SUM(A1)", tab + "x", cr + "x"]:
        assert csv_safe(text) == "'" + text
    for text in ["plain", "a=b", "", "'=quoted"]:
        assert csv_safe(text) == text
    assert csv_safe(-1.5) == -1.5                      # numbers are not text cells
    result = QualityEngine([NullRate(column="=cmd", max_pct=0)]).run(_csv_with_header("=cmd,ok"))
    out = results_csv(result)
    assert "'=cmd" in out and ",=cmd" not in out and '"=cmd' not in out


def _csv_with_header(header):
    import tempfile
    path = Path(tempfile.mkdtemp()) / "f.csv"
    path.write_text(header + chr(10) + "1,2" + chr(10))
    return str(path)


def test_explanation_is_rendered_as_plain_text(monkeypatch):
    nasty = "![x](http://evil.example/p.png) **bold** [link](http://evil.example)"

    class Nasty(FakeAgent):
        def explain_results(self, result, include_extremes=False, hide_column_names=False):
            return nasty

    at = _load(_app(Nasty(), monkeypatch), [NullRate(column=FIRST, max_pct=100)])
    at.button(key="quality_run").click().run()
    at.button(key="quality_explain").click().run()
    assert any(t.value == nasty for t in at.text)
    assert not any(nasty in m.value for m in at.markdown)


# ---- privacy guard -----------------------------------------------------------------------------

FORBIDDEN_MODULES = {"litellm", "openai", "anthropic", "requests", "httpx"}
FORBIDDEN_ATTRS = {"_call_llm", "completion", "suggest_configuration", "interpret_rule", "__getattribute__"}
INTROSPECTION = {"getattr", "setattr", "delattr", "eval", "exec", "__import__"}


def llm_violations(source: str) -> list:
    """Everything in a UI module that could reach an LLM other than through the summary-only entry points."""
    found = []
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, ast.Import):
            found += [f"imports {a.name}" for a in n.names if a.name.split(".")[0] in FORBIDDEN_MODULES]
        elif isinstance(n, ast.ImportFrom) and n.module and n.module.split(".")[0] in FORBIDDEN_MODULES:
            found.append(f"imports {n.module}")
        elif isinstance(n, ast.Attribute) and n.attr in FORBIDDEN_ATTRS:
            found.append(f"uses .{n.attr}")
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in FORBIDDEN_ATTRS:
            found.append(f"names {n.value!r} as a string")            # getattr(agent, "_call_llm"), dict lookups
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FORBIDDEN_ATTRS:
            found.append(f"calls {n.func.id}()")
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in INTROSPECTION:
            found.append(f"calls {n.func.id}()")                      # dynamic access cannot be checked
    return found


@pytest.mark.parametrize("name", ["pages/quality.py", "quality_grid.py"])
def test_ui_can_reach_an_llm_only_through_the_summary_builders(name):
    assert llm_violations((ROOT / "ui" / name).read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("snippet", [
    'agent._call_llm("x")',
    'getattr(agent, "_call_llm")("x")',
    'fn = getattr(agent, name)',
    'agent.__getattribute__("_call_llm")',
    'import litellm',
    'from litellm import completion',
    'import requests',
    'completion(model="m", messages=[])',
    'agent.suggest_configuration(a, b)',
])
def test_the_guard_catches_the_obvious_bypasses(snippet):
    assert llm_violations(snippet), snippet


def test_the_guard_allows_the_two_summary_entry_points():
    assert llm_violations("agent.suggest_checks(profile)" + chr(10) + "agent.explain_results(result)") == []


def test_completion_is_only_called_inside_ai():
    """The single place that sends a prompt is ai/agent.py; nothing else in the project may call completion()."""
    skip = {"venv", ".git", "tests", "ai", "__pycache__", "node_modules", ".pytest_cache"}
    offenders = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if set(rel.parts[:-1]) & skip:
            continue
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8", errors="replace"))):
            if isinstance(n, ast.Call):
                f = n.func
                if (isinstance(f, ast.Name) and f.id == "completion") or                         (isinstance(f, ast.Attribute) and f.attr == "completion"):
                    offenders.append(f"{rel}:{n.lineno}")
    assert offenders == []
