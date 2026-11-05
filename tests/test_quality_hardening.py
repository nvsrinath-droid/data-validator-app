"""Regression tests for the review of feat/data-quality. Each section is one finding, with its repro."""
import numpy as np
import pandas as pd
import pytest

from core.normalize import Kind
from core.quality.engine import QualityEngine
from core.quality.profile import profile_file
from core.quality.specs import Distinct, NullRate, TypeDrift
from test_quality import FORMATS, write


def only(result):
    assert len(result.results) == 1
    return result.results[0]


# ---- #1 a late bad value must not make DuckDB's CSV type guess fail the load ------------------

def test_late_bad_value_in_a_large_csv_is_reported_not_fatal(tmp_path):
    frame = pd.DataFrame({"V": [str(i) for i in range(30000)] + ["N/A"]})   # past DuckDB's sniffing window
    path = write(tmp_path, frame, "csv")
    r = only(QualityEngine([TypeDrift(column="V", expected=Kind.NUMERIC)]).run(path))
    assert (r.status, r.violations) == ("fail", 1)
    assert list(r.sample["value"]) == ["N/A"]


def test_csv_values_are_not_reinterpreted(tmp_path):
    """Leading zeros and padded numbers survive: nothing is guessed before the Kind rules see the text."""
    path = write(tmp_path, pd.DataFrame({"Code": ["007", "010"], "Amt": ["1.50", "2"]}), "csv")
    p = profile_file(path)
    assert p.column("Code").kind == Kind.NUMERIC and p.column("Code").min == "7.0"   # numeric by the shared rule
    r = only(QualityEngine([Distinct(column="Code", unique=True)]).run(path))
    assert r.status == "pass"


def test_excel_column_mixing_number_and_text_cells(tmp_path):
    frame = pd.DataFrame({"V": pd.Series([1, 2, "x", 4, "N/A"], dtype="object")})
    path = write(tmp_path, frame, "xlsx")
    r = only(QualityEngine([TypeDrift(column="V", expected=Kind.NUMERIC)]).run(path))
    assert (r.status, r.violations) == ("fail", 2)


def test_excel_and_csv_agree_on_na_tokens(tmp_path):
    frame = pd.DataFrame({"V": ["1", "N/A", "NA", "null", "", "2"]})
    views = []
    for fmt in FORMATS:
        p = profile_file(write(tmp_path, frame, fmt)).column("V")
        views.append((p.kind, p.null_count, p.non_null_count))
    assert views[0] == views[1] == (Kind.STRING, 1, 5)


# ---- #4 unparseable values are not false duplicates ------------------------------------------

def test_unparseable_values_are_not_counted_as_duplicates(tmp_path):
    ids = [str(i) for i in range(1500)] + ["N/A", "n/a"]     # 1,502 distinct values
    path = write(tmp_path, pd.DataFrame({"ID": ids}), "csv")
    assert profile_file(path).column("ID").distinct_count == 1502
    r = only(QualityEngine([Distinct(column="ID", unique=True)]).run(path))
    assert (r.status, r.violations) == ("pass", 0)


def test_repeated_unparseable_values_are_real_duplicates_with_a_sample(tmp_path):
    ids = [str(i) for i in range(1500)] + ["N/A", "N/A ", "7.0"]   # padded N/A repeats; 7.0 repeats 7 numerically
    for fmt in FORMATS:
        r = only(QualityEngine([Distinct(column="ID", unique=True)]).run(write(tmp_path, pd.DataFrame({"ID": ids}), fmt)))
        assert (r.status, r.violations) == ("fail", 2), fmt
        assert sorted(r.sample["value"]) == ["7.0", "N/A"], fmt


def test_distinct_counts_parsed_and_unparsed_values_together(tmp_path):
    values = [str(i) for i in range(1000)] + ["1.0", "x", "x", None]     # kind is numeric from the first 1,000
    col = profile_file(write(tmp_path, pd.DataFrame({"V": values}), "csv")).column("V")
    assert col.kind == Kind.NUMERIC
    assert (col.non_null_count, col.distinct_count) == (1003, 1001)       # 1.0 repeats 1; x repeats x


# ---- #5 a huge max_age is a validation error, not an OverflowError ----------------------------

import json  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from pydantic import ValidationError  # noqa: E402

import ai.agent as agent_mod  # noqa: E402
from ai.agent import AIAgent  # noqa: E402
from core.quality.specs import Freshness, Outliers, QualityConfig, parse_age  # noqa: E402


def fake_completion(content, calls=None):
    def _completion(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return _completion


@pytest.fixture
def small_profile(tmp_path):
    return profile_file(write(tmp_path, pd.DataFrame({"Name": ["a", "b"], "Amt": [1, 2], "D": ["2024-01-01"] * 2}), "csv"))


@pytest.mark.parametrize("age", ["99999999999d", "9" * 400 + "d", "36501d", "876001h"])
def test_oversized_ages_are_validation_errors(age):
    with pytest.raises(ValidationError):
        Freshness(column="D", max_age=age)
    with pytest.raises(ValidationError):
        QualityConfig.model_validate({"checks": [{"type": "freshness", "column": "D", "max_age": age}]})
    with pytest.raises(ValueError, match="too large"):
        parse_age(age)


def test_the_largest_allowed_age_still_works():
    assert parse_age("36500d").days == 36500


def test_oversized_age_from_the_llm_drops_that_suggestion_only(monkeypatch, small_profile):
    out = json.dumps({"checks": [{"type": "freshness", "column": "D", "max_age": "99999999999d"},
                                 {"type": "null_rate", "column": "Name"}]})
    monkeypatch.setattr(agent_mod, "completion", fake_completion(out))
    checks, notes = AIAgent("openai/gpt-5", "k").suggest_checks(small_profile)
    assert [c.type for c in checks] == ["null_rate"] and len(notes) == 1


def test_oversized_age_in_a_check_file_is_a_clean_cli_error(tmp_path, capsys):
    from quality_cli import quality_main
    checks = tmp_path / "c.json"
    checks.write_text(json.dumps({"checks": [{"type": "freshness", "column": "D", "max_age": "99999999999d"}]}))
    data = write(tmp_path, pd.DataFrame({"D": ["2024-01-01"]}), "csv")
    args = SimpleNamespace(profile=False, suggest_checks=False, quality=str(checks), file1=data, ref=None,
                           as_of=None, baseline=None, save_baseline=None, output=str(tmp_path / "o"), explain=False, strict=False)
    assert quality_main(args, None) == 2
    assert "Configuration error" in capsys.readouterr().out


# ---- #6 infinite and NaN numbers are rejected, and non-finite data cannot break outliers -------

def test_infinite_and_nan_thresholds_are_rejected_when_parsed_from_json():
    for raw in ('{"type":"outliers","column":"A","k":Infinity}', '{"type":"outliers","column":"A","k":NaN}',
                '{"type":"null_rate","column":"A","max_pct":NaN}', '{"type":"null_rate","column":"A","max_pct":Infinity}',
                '{"type":"type_drift","column":"A","max_pct":NaN}'):
        with pytest.raises(ValidationError):
            QualityConfig.model_validate({"checks": [json.loads(raw)]})
    with pytest.raises(ValidationError):
        Outliers(column="A", k=float("inf"))


def test_infinite_threshold_from_the_llm_is_dropped(monkeypatch, small_profile):
    out = '{"checks": [{"type": "outliers", "column": "Amt", "k": Infinity}, {"type": "null_rate", "column": "Name"}]}'
    monkeypatch.setattr(agent_mod, "completion", fake_completion(out))
    checks, notes = AIAgent("openai/gpt-5", "k").suggest_checks(small_profile)
    assert [c.type for c in checks] == ["null_rate"] and len(notes) == 1


def test_non_finite_values_in_the_data_do_not_break_outliers(tmp_path):
    values = [str(10 + i % 5) for i in range(1200)] + ["1000", "inf", "NaN", "-inf"]   # kind is numeric from the sample
    path = write(tmp_path, pd.DataFrame({"Amt": values}), "csv")
    for method in ("iqr", "zscore"):
        r = only(QualityEngine([Outliers(column="Amt", method=method, k=3)]).run(path))
        assert (r.status, r.violations) == ("fail", 1), (method, r.message)
        assert [float(v) for v in r.sample["value"]] == [1000.0]


# ---- #7 IQR on tied values is inconclusive, with the reason and the z-score suggestion ---------

def tied(n_ties, tie_value, others):
    return [tie_value] * n_ties + list(others)


@pytest.mark.parametrize("name,values,share", [
    ("80% zeros", tied(800, 0, [1 + i % 50 for i in range(200)]), "80%"),
    ("60% tens", tied(600, 10, [9, 11] * 200), "60%"),
    ("lone extreme", [1, 1, 1, 1, 100], "80%"),
])
def test_iqr_with_mostly_equal_values_is_inconclusive(tmp_path, name, values, share):
    for fmt in FORMATS:
        res = QualityEngine([Outliers(column="Amt")]).run(write(tmp_path, pd.DataFrame({"Amt": values}), fmt))
        r = only(res)
        assert (r.status, r.violations, r.metric) == ("inconclusive", 0, None), (name, fmt, r.message)
        assert share in r.message and "zscore" in r.message and "IQR is 0" in r.message
        assert not res.has_failures


def test_z_score_is_the_suggested_way_out(tmp_path):
    values = tied(800, 0, [1 + i % 5 for i in range(199)] + [5000])
    path = write(tmp_path, pd.DataFrame({"Amt": values}), "csv")
    assert only(QualityEngine([Outliers(column="Amt")]).run(path)).status == "inconclusive"
    r = only(QualityEngine([Outliers(column="Amt", method="zscore")]).run(path))
    assert r.status == "fail" and r.violations >= 1 and 5000.0 in [float(v) for v in r.sample["value"]]


def test_constant_column_passes_and_ordinary_spread_still_uses_iqr(tmp_path):
    assert only(QualityEngine([Outliers(column="A")]).run(write(tmp_path, pd.DataFrame({"A": [7] * 30}), "csv"))).status == "pass"
    spread = pd.DataFrame({"A": [10, 11, 12, 13, 14, 15, 16, 17, 500]})
    r = only(QualityEngine([Outliers(column="A")]).run(write(tmp_path, spread, "csv")))
    assert (r.status, r.violations) == ("fail", 1)


def test_inconclusive_is_reported_by_the_cli_without_failing_the_run(tmp_path, capsys):
    from quality_cli import quality_main
    checks = tmp_path / "c.json"
    checks.write_text(json.dumps({"checks": [{"type": "outliers", "column": "Amt"}]}))
    data = write(tmp_path, pd.DataFrame({"Amt": tied(80, 0, range(1, 21))}), "csv")
    args = SimpleNamespace(profile=False, suggest_checks=False, quality=str(checks), file1=data, ref=None,
                           as_of=None, baseline=None, save_baseline=None, output=str(tmp_path / "o"), explain=False, strict=False)
    assert quality_main(args, None) == 0
    out = capsys.readouterr().out
    assert "[INCL]" in out and "1 inconclusive" in out and "0 failed" in out


# ---- #2 header rows that are really data, #3 freshness metric, #12 db types, #14 coverage ------

import duckdb  # noqa: E402
from datetime import datetime  # noqa: E402

from ai.quality_summary import ColumnAliases, looks_like_data, profile_summary, result_summary  # noqa: E402
from core.quality.profile import profile_table  # noqa: E402
from core.quality.specs import CheckResult, QualityResult, RefIntegrity  # noqa: E402

SECRET_TEXT, SECRET_NUMBER = "ACME-SECRET", "918273645"


def prompt_json(calls) -> str:
    return json.dumps([c["messages"] for c in calls])


@pytest.mark.parametrize("name,flag", [
    ("Salary", False), ("Cust ID", False), ("AN8", False), ("order_date", False), ("Unnamed: 3", False),
    ("918273645", True), ("918273645.0", True), ("-12.5", True), ("1e5", True), ("2024-01-15", True),
    ("2024-01-15 10:00:00", True), ("", True), ("   ", True), ("x" * 65, True),
])
def test_names_that_look_like_data(name, flag):
    assert looks_like_data(name) is flag


@pytest.fixture
def headerless(tmp_path):
    """No header row: the first data row becomes the 'column names' (this is the repro from the review)."""
    path = tmp_path / "nohdr.xlsx"
    pd.DataFrame([[SECRET_TEXT, float(SECRET_NUMBER)], ["Globex", 12.0], ["Initech", 13.0]]).to_excel(
        path, index=False, header=False)
    return str(path)


def test_headerless_file_really_exposes_data_as_column_names(headerless):
    names = [c.name for c in profile_file(headerless).columns]
    assert SECRET_TEXT in names and any(SECRET_NUMBER in n for n in names)        # guards the guard


def test_headerless_file_names_are_replaced_in_the_suggest_prompt(monkeypatch, headerless):
    calls = []
    monkeypatch.setattr(agent_mod, "completion", fake_completion('{"checks": []}', calls))
    AIAgent("openai/gpt-5", "k").suggest_checks(profile_file(headerless))
    sent = prompt_json(calls)
    assert SECRET_TEXT not in sent and SECRET_NUMBER not in sent
    assert "col_1" in sent and "col_2" in sent


def test_placeholders_map_back_to_the_real_columns(monkeypatch, headerless):
    profile = profile_file(headerless)
    real = [c.name for c in profile.columns]
    out = json.dumps({"checks": [{"type": "null_rate", "column": "col_2", "max_pct": 5},
                                 {"type": "null_rate", "column": SECRET_TEXT},          # a real name was never sent
                                 {"type": "null_rate", "column": "col_9"}]})
    monkeypatch.setattr(agent_mod, "completion", fake_completion(out))
    checks, notes = AIAgent("openai/gpt-5", "k").suggest_checks(profile)
    assert [c.column for c in checks] == [real[1]]
    assert len(notes) == 2 and all("unknown column" in n for n in notes)


def test_explain_prompt_hides_data_like_names(headerless):
    real = [c.name for c in profile_file(headerless).columns]
    result = QualityEngine([NullRate(column=real[0]), NullRate(column=real[1])]).run(headerless)
    summary = json.dumps(result_summary(result))
    assert SECRET_TEXT not in summary and SECRET_NUMBER not in summary
    assert {c["check"]["column"] for c in json.loads(summary)["checks"]} == {"col_1", "col_2"}


def test_a_few_data_like_names_are_replaced_individually():
    a = ColumnAliases(["Name", "Amt", "918273645", "Dept"])         # 1 of 4 looks like data
    assert [a.alias(n) for n in ("Name", "Amt", "918273645", "Dept")] == ["Name", "Amt", "col_3", "Dept"]
    assert a.restore("col_3") == "918273645" and a.restore("Name") == "Name"
    assert a.restore("918273645") is None and a.restore("Invented") is None


def test_a_placeholder_never_collides_with_a_real_name():
    a = ColumnAliases(["col_2", "918273645", "Dept", "Amt"])        # col_2 is real; position 2 needs a placeholder
    assert a.alias("918273645") != "col_2" and a.restore(a.alias("918273645")) == "918273645"
    assert a.restore("col_2") == "col_2"


def test_hide_column_names_replaces_every_name(monkeypatch, tmp_path):
    path = write(tmp_path, pd.DataFrame({"Salary": [1, 2], "SSN": ["a", "b"]}), "csv")
    calls = []
    monkeypatch.setattr(agent_mod, "completion",
                        fake_completion('{"checks": [{"type": "null_rate", "column": "col_2"}]}', calls))
    checks, _ = AIAgent("openai/gpt-5", "k").suggest_checks(profile_file(path), hide_column_names=True)
    assert "Salary" not in prompt_json(calls) and "SSN" not in prompt_json(calls)
    assert [c.column for c in checks] == ["SSN"]
    result = QualityEngine([NullRate(column="SSN")]).run(path)
    assert "SSN" not in json.dumps(result_summary(result, hide_names=True))
    assert "SSN" in json.dumps(result_summary(result))             # names are sent when not hidden


def test_reference_columns_that_look_like_data_are_replaced(tmp_path):
    ref = write(tmp_path, pd.DataFrame({"2024-01-15": ["C1"]}), "csv", name="ref")
    data = write(tmp_path, pd.DataFrame({"Cust": ["C1", "C2"]}), "csv")
    result = QualityEngine([RefIntegrity(column="Cust", ref_name="p", ref_column="2024-01-15")],
                           references={"p": ref}).run(data)
    summary = json.dumps(result_summary(result))
    assert "2024-01-15" not in summary and "ref_col_1" in summary


def test_freshness_metric_is_withheld_unless_opted_in(tmp_path, monkeypatch):
    data = write(tmp_path, pd.DataFrame({"D": ["2026-10-01 09:30:00"]}), "csv")
    result = QualityEngine([Freshness(column="D", max_age="1h")], as_of=datetime(2026, 11, 4, 12)).run(data)
    assert result.results[0].metric == pytest.approx(818.5)                    # measured locally
    default = result_summary(result)["checks"][0]
    assert default["metric"] is None and default["status"] == "fail" and default["check"]["max_age"] == "1h"
    assert result_summary(result, include_extremes=True)["checks"][0]["metric"] == pytest.approx(818.5)
    calls = []                                                                 # the agent passes the choice through
    monkeypatch.setattr(agent_mod, "completion", fake_completion("ok", calls))
    agent = AIAgent("openai/gpt-5", "k")
    agent.explain_results(result)
    assert "818.5" not in prompt_json(calls)
    agent.explain_results(result, include_extremes=True)
    assert "818.5" in prompt_json(calls[-1:])


def test_other_metrics_are_still_sent(tmp_path):
    data = write(tmp_path, pd.DataFrame({"A": [None, 1, 2, 3]}), "csv")
    result = QualityEngine([NullRate(column="A")]).run(data)
    assert result_summary(result)["checks"][0]["metric"] == 25.0


def test_enum_type_names_are_not_sent(monkeypatch):
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TYPE mood AS ENUM ('ZXQ-ENUM-1', 'ZXQ-ENUM-2')")
    conn.execute("CREATE TABLE t (m mood)")
    conn.execute("INSERT INTO t VALUES ('ZXQ-ENUM-1'), ('ZXQ-ENUM-2')")
    profile = profile_table(conn, "t")
    assert "ZXQ-ENUM-1" in profile.columns[0].db_type                          # the type name spells the values out
    assert "ZXQ-ENUM" not in json.dumps(profile_summary(profile))
    calls = []
    monkeypatch.setattr(agent_mod, "completion", fake_completion('{"checks": []}', calls))
    AIAgent("openai/gpt-5", "k").suggest_checks(profile)
    assert "ZXQ-ENUM" not in prompt_json(calls)
    conn.close()


def test_error_results_never_put_their_message_in_the_prompt(monkeypatch):
    leaky = "Conversion Error: could not convert string 'ZXQ-SECRET-7731' to DOUBLE"
    result = QualityResult(row_count=3, columns=["A"],
                           results=[CheckResult(NullRate(column="A"), "error", message=leaky)])
    calls = []
    monkeypatch.setattr(agent_mod, "completion", fake_completion("ok", calls))
    AIAgent("openai/gpt-5", "k").explain_results(result)
    assert "ZXQ-SECRET-7731" not in prompt_json(calls) and "Conversion" not in prompt_json(calls)


def test_a_large_file_with_markers_reaches_the_prompts_as_summaries_only(tmp_path, monkeypatch):
    n = 30000                                                   # past DuckDB's CSV sniffing window
    frame = pd.DataFrame({
        "Name": [f"row-{i}" for i in range(n)] + ["ZXQ-SECRET-7731", "ZXQ-SECRET-7731"],
        "Salary": [str(50 + i % 7) for i in range(n)] + ["918273645", "N/A"],
        "Updated": ["2031-07-01"] * n + ["2031-07-19", "2031-07-19"],
    })
    data = write(tmp_path, frame, "csv", name="people_ZXQ_PATH")
    checks = [Distinct(column="Name", unique=True), TypeDrift(column="Salary", expected=Kind.NUMERIC),
              Outliers(column="Salary", method="zscore"), Freshness(column="Updated", max_age="1h")]
    result = QualityEngine(checks, as_of=datetime(2031, 7, 20)).run(data)
    assert result.row_count == n + 2 and all(r.status == "fail" for r in result.results[:2])
    calls = []
    monkeypatch.setattr(agent_mod, "completion", fake_completion('{"checks": []}', calls))
    agent = AIAgent("openai/gpt-5", "sk-key-123")
    agent.suggest_checks(profile_file(data))
    agent.explain_results(result)
    sent = prompt_json(calls) + json.dumps([{k: v for k, v in c.items() if k != "messages"} for c in calls])
    for secret in ("ZXQ-SECRET-7731", "918273645", "2031-07-19", "ZXQ_PATH", str(tmp_path)):
        assert secret not in sent, secret
    assert "Salary" in sent and "Updated" in sent                # real, non-data-like names are still sent


# ---- CI on Python 3.12 (pandas 3, duckdb 2): an open result blocked loading an Excel reference ----

def test_fetch_one_leaves_the_connection_usable_for_registering_a_dataframe():
    """DuckDB 2.x raises 'Resource In Use Error' on register() while a fetchone() result is still open."""
    from core.quality.profile import fetch_one
    conn = duckdb.connect(":memory:")
    assert fetch_one(conn, "SELECT x FROM range(1000) t(x)") == (0,)       # many rows, only the first is wanted
    conn.register("late_df", pd.DataFrame({"a": [1]}))
    assert conn.execute("SELECT a FROM late_df").fetchall() == [(1,)]
    conn.close()


def test_excel_reference_loads_after_earlier_checks_on_the_same_connection(tmp_path):
    data = write(tmp_path, pd.DataFrame({"Cust": ["C1", "C9"], "Amt": [1, 2]}), "xlsx")
    ref = write(tmp_path, pd.DataFrame({"ID": ["C1"]}), "xlsx", name="ref")
    checks = [NullRate(column="Amt"), Distinct(column="Cust", unique=True),
              RefIntegrity(column="Cust", ref_name="p", ref_column="ID")]
    res = QualityEngine(checks, references={"p": ref}).run(data)
    assert [r.status for r in res.results] == ["pass", "pass", "fail"]


# ---- re-review #1: a check that names a column the table does not have must not send that name ----

def explain_prompt(monkeypatch, result, **kw):
    calls = []
    monkeypatch.setattr(agent_mod, "completion", fake_completion("ok", calls))
    AIAgent("openai/gpt-5", "k").explain_results(result, **kw)
    return calls[0]["messages"][0]["content"]


@pytest.fixture
def typo_result(tmp_path):
    data = write(tmp_path, pd.DataFrame({"Salary": [1, 2], "Dept": ["a", "b"]}), "csv")
    checks = [NullRate(column="Salary"), NullRate(column="Typo_SSN"), NullRate(column="2031-07-19"),
              Distinct(column="Typo_SSN", unique=True)]
    return QualityEngine(checks).run(data)


@pytest.mark.parametrize("hide", [False, True])
def test_unknown_column_names_are_masked_in_the_prompt(monkeypatch, typo_result, hide):
    assert [r.status for r in typo_result.results] == ["pass", "error", "error", "error"]     # they really are unknown
    sent = explain_prompt(monkeypatch, typo_result, hide_column_names=hide)
    assert "Typo_SSN" not in sent and "2031-07-19" not in sent
    columns = [c["check"]["column"] for c in json.loads(sent.split("\n\n")[1].strip())["checks"]]
    assert columns[1] == columns[3] != columns[2]               # same unknown name -> same placeholder, others differ
    assert all(c.startswith("unknown_col_") for c in columns[1:])
    assert ("Salary" in sent) is (not hide)                     # real names are still sent unless hidden


def test_a_result_without_a_column_list_masks_every_name():
    result = QualityResult(row_count=2, columns=[], results=[
        CheckResult(NullRate(column="Salary"), "pass", 0.0, 0), CheckResult(NullRate(column="918273645"), "pass", 0.0, 0)])
    sent = json.dumps(result_summary(result))
    assert "Salary" not in sent and "918273645" not in sent and "unknown_col_2" in sent


def test_placeholders_for_unknown_names_do_not_collide_with_real_columns():
    result = QualityResult(row_count=1, columns=["unknown_col_1", "A"], results=[
        CheckResult(NullRate(column="Typo"), "error"), CheckResult(NullRate(column="unknown_col_1"), "pass")])
    a, b = [c["check"]["column"] for c in result_summary(result)["checks"]]
    assert a != b and b == "unknown_col_1"


def test_unverified_reference_names_and_columns_are_masked(tmp_path):
    data = write(tmp_path, pd.DataFrame({"Cust": ["C1", "C9"]}), "csv")
    ref = write(tmp_path, pd.DataFrame({"ID": ["C1"]}), "csv", name="ref")
    checks = [RefIntegrity(column="Cust", ref_name="customers", ref_column="ID"),          # real
              RefIntegrity(column="Cust", ref_name="customers", ref_column="Typo_Col"),    # typo in the column
              RefIntegrity(column="Cust", ref_name="Typo_Ref", ref_column="ID")]           # reference never provided
    result = QualityEngine(checks, references={"customers": ref}).run(data)
    assert [r.status for r in result.results] == ["fail", "error", "error"]
    sent = json.dumps(result_summary(result))
    assert "Typo_Col" not in sent and "Typo_Ref" not in sent
    first = result_summary(result)["checks"][0]["check"]
    assert (first["ref_name"], first["ref_column"]) == ("customers", "ID")
    assert "ID" not in json.dumps(result_summary(result, hide_names=True)["checks"][0]["check"]["ref_column"])


# ---- re-review #3: timestamps with a UTC offset are converted to UTC, so freshness is correct ------------------

from datetime import timedelta, timezone  # noqa: E402

from core.quality.specs import Freshness  # noqa: E402

AS_OF_UTC = datetime(2026, 11, 4, 12, 0, 0)


def newest_age_hours(tmp_path, values, fmt="csv", max_age="1000d", as_of=AS_OF_UTC):
    path = write(tmp_path, pd.DataFrame({"D": values}), fmt)
    r = only(QualityEngine([Freshness(column="D", max_age=max_age)], as_of=as_of).run(path))
    return r.metric, r


@pytest.mark.parametrize("value,expected_utc_hour", [
    ("2026-11-04T10:00:00+05:00", 5.0),       # 05:00 UTC -> 7h before 12:00
    ("2026-11-04T10:00:00-08:00", 18.0),      # 18:00 UTC -> 6h in the future
    ("2026-11-04T01:00:00Z", 1.0),
    ("2026-11-04 10:00:00 +05:00", 5.0),      # space before the offset
    ("2026-11-04T10:00+05:30", 4.5),          # no seconds, half-hour offset
    ("2026-11-04T10:00Z", 10.0),
    ("2026-11-04T10:00:00+0530", 4.5),        # offset without a colon
    ("2026-11-04T10:00:00.250-08", 18.00007),  # fractional seconds, hour-only offset
    ("2026-11-04 10:00:00", 10.0),            # no offset: taken as UTC, unchanged
    ("2026-11-04", 0.0),
])
@pytest.mark.parametrize("fmt", FORMATS)
def test_offsets_are_converted_to_utc(tmp_path, value, expected_utc_hour, fmt):
    metric, r = newest_age_hours(tmp_path, [value], fmt)
    assert metric == pytest.approx(12.0 - expected_utc_hour, abs=1e-3), r.message
    assert "UTC" in r.message


def test_the_newest_value_is_chosen_after_conversion(tmp_path):
    # 23:00-08:00 on Nov 4 is 07:00 UTC on Nov 5, later than the plain 03:00 on Nov 5.
    metric, r = newest_age_hours(tmp_path, ["2026-11-04T23:00:00-08:00", "2026-11-05 03:00:00", "2026-11-04T20:00:00+00:00"],
                                 as_of=datetime(2026, 11, 5, 12, 0, 0))
    assert metric == pytest.approx(5.0) and "2026-11-05 07:00:00 UTC" in r.message


def test_the_result_does_not_depend_on_the_machines_time_zone(tmp_path, monkeypatch):
    import duckdb
    results = []
    real_connect = duckdb.connect

    def connect_in(tz):
        def _connect(*a, **k):
            conn = real_connect(*a, **k)
            conn.execute(f"SET TimeZone='{tz}'")
            return conn
        return _connect

    for tz in ("UTC", "America/Los_Angeles", "Asia/Kolkata"):
        monkeypatch.setattr("core.quality.engine.duckdb.connect", connect_in(tz))
        results.append(newest_age_hours(tmp_path, ["2026-11-04T10:00:00+05:00", "2026-11-04 03:00:00"])[0])
    assert results == [pytest.approx(7.0)] * 3


def test_freshness_passes_and_fails_on_the_converted_age(tmp_path):
    value = ["2026-11-04T10:00:00+05:00"]                     # 05:00 UTC, 7h before AS_OF_UTC
    assert only(QualityEngine([Freshness(column="D", max_age="8h")], as_of=AS_OF_UTC).run(
        write(tmp_path, pd.DataFrame({"D": value}), "csv"))).status == "pass"
    assert only(QualityEngine([Freshness(column="D", max_age="6h")], as_of=AS_OF_UTC).run(
        write(tmp_path, pd.DataFrame({"D": value}), "csv"))).status == "fail"
    # the old behaviour dropped the offset: 10:00 looked 2h old and a 6h limit would have passed


def test_default_now_is_utc_whatever_the_offset_of_the_data(tmp_path):
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    for tz_hours in (0, 5, -8):
        local = one_hour_ago.astimezone(timezone(timedelta(hours=tz_hours)))
        value = local.strftime("%Y-%m-%dT%H:%M:%S%z")                       # e.g. 2026-11-04T10:00:00+0500
        metric, _ = newest_age_hours(tmp_path, [value], as_of=None)
        assert metric == pytest.approx(1.0, abs=0.2), (value, metric)


def test_an_aware_as_of_is_converted_to_utc(tmp_path):
    data = write(tmp_path, pd.DataFrame({"D": ["2026-11-04 05:00:00"]}), "csv")
    aware = datetime(2026, 11, 4, 17, 0, 0, tzinfo=timezone(timedelta(hours=5)))            # = 12:00 UTC
    r = only(QualityEngine([Freshness(column="D")], as_of=aware).run(data))
    assert r.metric == pytest.approx(7.0)


def test_type_drift_accepts_offsets_as_dates_and_still_catches_junk(tmp_path):
    frame = pd.DataFrame({"D": ["2026-11-04T10:00:00+05:00", "2026-11-04T01:00:00Z", "2026-11-04 10:00:00", "bad+05:00"]})
    r = only(QualityEngine([TypeDrift(column="D", expected=Kind.DATE)]).run(write(tmp_path, frame, "csv")))
    assert (r.status, r.violations) == ("fail", 1) and list(r.sample["value"]) == ["bad+05:00"]


def test_the_comparison_engines_date_handling_is_untouched():
    from core.engines.sql_builder import DuckDBDialect
    assert "timezone" not in DuckDBDialect().to_ts("x")
