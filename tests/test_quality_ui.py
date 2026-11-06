"""The Data Quality tier: the checks grid, the page end to end (stubbed AI agent), and the privacy guard."""
import ast
from pathlib import Path

import pandas as pd
import pytest

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


def test_explain_gets_the_result_object_and_the_flags(monkeypatch):
    at = _load(_app(FakeAgent(), monkeypatch), [NullRate(column=FIRST, max_pct=100)])
    at.button(key="quality_run").click().run()
    at.checkbox(key="quality_include_extremes").check().run()
    at.button(key="quality_explain").click().run()
    assert not at.exception, at.exception
    kind, result, extremes, hide = FakeAgent.calls[-1]
    assert kind == "explain" and isinstance(result, QualityResult)
    assert (extremes, hide) == (True, False)
    assert any("Everything looks fine." in m.value for m in at.markdown)


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


# ---- privacy guard -----------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["pages/quality.py", "quality_grid.py"])
def test_ui_can_reach_an_llm_only_through_the_summary_builders(name):
    tree = ast.parse((ROOT / "ui" / name).read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
               {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(m and m.split(".")[0] in ("litellm", "openai", "anthropic", "requests", "httpx") for m in imported)
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & {"_call_llm", "completion", "suggest_configuration", "interpret_rule"}
