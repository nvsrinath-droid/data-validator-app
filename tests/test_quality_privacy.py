"""Bring-your-own-key LLM calls for data quality send summaries only, never rows or values."""
import json
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

import ai.agent as agent_mod
from ai.agent import AIAgent
from ai.quality_summary import profile_summary, result_summary
from core.quality.engine import QualityEngine
from core.quality.profile import profile_file
from core.quality.specs import Distinct, Freshness, NullRate, Outliers, RefIntegrity

NAME_MARKER = "ZXQ-SECRET-7731"
SALARY_MARKER = "918273645"
DATE_MARKER = "2031-07-19"
ORPHAN_MARKER = "ORPH-5521"
MARKERS = [NAME_MARKER, SALARY_MARKER, DATE_MARKER, ORPHAN_MARKER]
AS_OF = datetime(2031, 7, 20, 0, 0, 0)


def fake_completion(content, calls):
    def _completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return _completion


@pytest.fixture
def scenario(tmp_path):
    """A table whose failing checks all have samples/messages that quote the marker values."""
    people = pd.DataFrame({
        "Name": [NAME_MARKER, NAME_MARKER, None, "Ann", "Bob", "Cy", "Di", "Ed", "Flo", "Gus"],
        "Salary": [50, 52, 51, 49, 50, 53, 51, 52, 50, int(SALARY_MARKER)],
        "Updated": ["2031-07-01"] * 9 + [DATE_MARKER],
        "Dept": ["D1"] * 9 + [ORPHAN_MARKER],
    })
    depts = pd.DataFrame({"Code": ["D1", "D2"]})
    data, ref = tmp_path / "people.csv", tmp_path / "departments.csv"
    people.to_csv(data, index=False)
    depts.to_csv(ref, index=False)
    checks = [NullRate(column="Name"), Distinct(column="Name", unique=True), Outliers(column="Salary"),
              Freshness(column="Updated", max_age="1h"),
              RefIntegrity(column="Dept", ref_name="departments", ref_column="Code")]
    result = QualityEngine(checks, references={"departments": str(ref)}, as_of=AS_OF).run(str(data))
    return SimpleNamespace(path=str(data), ref=str(ref), tmp_path=tmp_path, result=result, profile=profile_file(str(data)))


def prompt_text(calls) -> str:
    return json.dumps([m for c in calls for m in c["messages"]]) + json.dumps({k: v for c in calls for k, v in c.items()
                                                                              if k != "messages"})


def test_the_scenario_really_contains_the_markers_locally(scenario):
    """Guards the guard: the local result holds the markers, so a leak would be visible."""
    local = " ".join(r.message + r.sample.to_string() for r in scenario.result.results)
    for marker in MARKERS:
        assert marker in local, marker
    assert all(r.status == "fail" for r in scenario.result.results)


def test_suggest_checks_prompt_has_no_values(scenario, monkeypatch):
    calls = []
    monkeypatch.setattr(agent_mod, "completion", fake_completion('{"checks": []}', calls))
    AIAgent("openai/gpt-5", "sk-test-key").suggest_checks(scenario.profile, references=["departments"])
    sent = prompt_text(calls)
    for marker in MARKERS:
        assert marker not in sent, f"{marker} leaked into the suggest_checks prompt"
    assert "Salary" in sent and "null_pct" in sent            # the summary itself is there
    assert scenario.path not in sent and str(scenario.tmp_path) not in sent


def test_explain_prompt_has_no_values_samples_or_messages(scenario, monkeypatch):
    calls = []
    monkeypatch.setattr(agent_mod, "completion", fake_completion("Looks bad.", calls))
    out = AIAgent("openai/gpt-5", "sk-test-key").explain_results(scenario.result)
    assert out == "Looks bad."
    sent = prompt_text(calls)
    for marker in MARKERS:
        assert marker not in sent, f"{marker} leaked into the explain_results prompt"
    content = calls[0]["messages"][0]["content"]
    for r in scenario.result.results:                           # messages quote data, so none may be sent
        assert r.message not in content
    assert '"ref_integrity"' in content and '"violations"' in content
    assert str(scenario.tmp_path) not in sent


def test_extremes_are_opt_in_per_run(scenario, monkeypatch):
    default = json.dumps(profile_summary(scenario.profile))
    assert SALARY_MARKER not in default and DATE_MARKER not in default and '"min"' not in default
    opted_in = json.dumps(profile_summary(scenario.profile, include_extremes=True))
    assert SALARY_MARKER in opted_in and DATE_MARKER in opted_in
    # ...and the agent passes the flag through only when asked.
    calls = []
    monkeypatch.setattr(agent_mod, "completion", fake_completion('{"checks": []}', calls))
    agent = AIAgent("openai/gpt-5", "k")
    agent.suggest_checks(scenario.profile)
    assert SALARY_MARKER not in prompt_text(calls)
    agent.suggest_checks(scenario.profile, include_extremes=True)
    assert SALARY_MARKER in json.dumps(calls[-1]["messages"])


def test_result_summary_is_structured_counts_only(scenario):
    summary = result_summary(scenario.result)
    assert {c["check"]["type"] for c in summary["checks"]} == {"null_rate", "distinct", "outliers", "freshness",
                                                              "ref_integrity"}
    assert all(set(c) == {"check", "status", "metric", "violations"} for c in summary["checks"])


def test_api_key_goes_in_the_call_not_the_prompt(scenario, monkeypatch):
    calls = []
    monkeypatch.setattr(agent_mod, "completion", fake_completion('{"checks": []}', calls))
    AIAgent("openai/gpt-5", "sk-test-key").suggest_checks(scenario.profile)
    assert calls[0]["api_key"] == "sk-test-key"
    assert "sk-test-key" not in json.dumps(calls[0]["messages"])


# ---- LLM output is validated, never trusted ---------------------------------------------------

def suggest(monkeypatch, scenario, output, references=("departments",)):
    monkeypatch.setattr(agent_mod, "completion", fake_completion(output, []))
    return AIAgent("openai/gpt-5", "k").suggest_checks(scenario.profile, references=list(references))


def test_valid_suggestions_become_specs(monkeypatch, scenario):
    checks, notes = suggest(monkeypatch, scenario, json.dumps({"checks": [
        {"type": "null_rate", "column": "Name", "max_pct": 5},
        {"type": "outliers", "column": "Salary", "method": "zscore", "k": 3},
        {"type": "freshness", "column": "Updated", "max_age": "36h", "severity": "warn"},
        {"type": "ref_integrity", "column": "Dept", "ref_name": "departments", "ref_column": "Code"},
    ]}))
    assert [c.type for c in checks] == ["null_rate", "outliers", "freshness", "ref_integrity"] and notes == []


def test_fenced_json_is_accepted(monkeypatch, scenario):
    checks, _ = suggest(monkeypatch, scenario, '```json\n{"checks": [{"type": "null_rate", "column": "Name"}]}\n```')
    assert len(checks) == 1


@pytest.mark.parametrize("bad_item,why", [
    ({"type": "run_sql", "column": "Name", "sql": "DROP TABLE t"}, "invalid"),
    ({"type": "null_rate", "column": "Name", "sql": "SELECT 1"}, "invalid"),            # extra field
    ({"type": "ref_integrity", "column": "Dept", "ref_name": "departments", "ref_column": "C",
      "path": "C:/secrets.csv"}, "invalid"),                                           # a spec cannot carry a path
    ({"type": "null_rate", "column": "Invented"}, "unknown column"),
    ({"type": "outliers", "column": "Name"}, "non-numeric"),
    ({"type": "freshness", "column": "Salary"}, "non-date"),
    ({"type": "ref_integrity", "column": "Dept", "ref_name": "payroll", "ref_column": "X"}, "unknown reference"),
    ("not an object", "invalid"),
])
def test_bad_suggestions_are_dropped_and_good_ones_kept(monkeypatch, scenario, bad_item, why):
    good = {"type": "null_rate", "column": "Name", "max_pct": 10}
    checks, notes = suggest(monkeypatch, scenario, json.dumps({"checks": [bad_item, good]}))
    assert [c.type for c in checks] == ["null_rate"]
    assert len(notes) == 1 and why in notes[0]


@pytest.mark.parametrize("output", ["not json at all", '{"checks": "nope"}', "42"])
def test_unusable_output_raises(monkeypatch, scenario, output):
    with pytest.raises(ValueError):
        suggest(monkeypatch, scenario, output)


def test_suggestion_count_is_capped(monkeypatch, scenario):
    many = [{"type": "null_rate", "column": "Name"}] * 80
    checks, notes = suggest(monkeypatch, scenario, json.dumps({"checks": many}))
    assert len(checks) == 50 and any("Ignored 30" in n for n in notes)
