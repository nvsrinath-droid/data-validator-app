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
