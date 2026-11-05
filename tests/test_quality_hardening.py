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
                           as_of=None, baseline=None, save_baseline=None, output=str(tmp_path / "o"), explain=False)
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
