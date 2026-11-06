"""Single-table data quality on DuckDB. Every scenario runs from CSV and from XLSX, which must agree."""
import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from core.normalize import Kind
from core.quality.profile import profile_file
from core.quality.specs import Freshness, NullRate, Outliers, QualityConfig, parse_age

FORMATS = ["csv", "xlsx"]


def write(tmp_path, frame: pd.DataFrame, fmt: str, name: str = "data") -> str:
    path = tmp_path / f"{name}.{fmt}"
    if fmt == "csv":
        frame.to_csv(path, index=False)
    else:
        frame.to_excel(path, index=False)
    return str(path)


def profile_both(tmp_path, frame: pd.DataFrame):
    """Profile the same data from CSV and XLSX; the two must agree on everything but the storage type."""
    profiles = {fmt: profile_file(write(tmp_path, frame, fmt)) for fmt in FORMATS}

    def view(p):
        return {c.name: (c.kind, c.non_null_count, c.null_count, c.null_pct, c.distinct_count,
                         c.nonconforming_count) for c in p.columns}

    assert view(profiles["xlsx"]) == view(profiles["csv"]), "xlsx disagrees with csv"
    return profiles["csv"]


# ---- specs are validated data ----------------------------------------------------------

def test_specs_parse_from_json_by_type():
    cfg = QualityConfig.model_validate({"checks": [
        {"type": "null_rate", "column": "A", "max_pct": 5},
        {"type": "freshness", "column": "D", "max_age": "36h", "severity": "warn"},
    ]})
    assert isinstance(cfg.checks[0], NullRate) and isinstance(cfg.checks[1], Freshness)
    assert cfg.checks[1].max_age_delta.total_seconds() == 36 * 3600


@pytest.mark.parametrize("bad", [
    {"type": "run_sql", "column": "A"},                          # unknown check type
    {"type": "null_rate", "column": "A", "sql": "DROP TABLE t"},  # extra field
    {"type": "null_rate", "column": "A", "max_pct": 150},        # out of range
    {"type": "freshness", "column": "D", "max_age": "soon"},     # unparsable age
    {"type": "ref_integrity", "column": "A", "ref_name": "r", "ref_column": "B", "path": "C:/secret.csv"},
])
def test_invalid_specs_are_rejected(bad):
    with pytest.raises(ValidationError):
        QualityConfig.model_validate({"checks": [bad]})


def test_outlier_default_thresholds():
    assert Outliers(column="A").threshold == 1.5
    assert Outliers(column="A", method="zscore").threshold == 3.0
    assert Outliers(column="A", method="zscore", k=2.5).threshold == 2.5


@pytest.mark.parametrize("text,seconds", [("90m", 5400), ("36h", 129600), ("2d", 172800), ("1.5h", 5400)])
def test_parse_age(text, seconds):
    assert parse_age(text).total_seconds() == seconds


# ---- profile: nulls, distincts, kinds ---------------------------------------------------

def test_null_blank_and_padded_blank_all_count_as_null(tmp_path):
    frame = pd.DataFrame({"ID": [1, 2, 3, 4], "Note": ["x", None, "   ", ""]})
    col = profile_both(tmp_path, frame).column("Note")
    assert (col.null_count, col.non_null_count, col.null_pct) == (3, 1, 75.0)


def test_distinct_counts_use_the_inferred_kind(tmp_path):
    # 100, 100.0 and "100.00" are the same number; "a" and "A " differ only by padding for strings.
    frame = pd.DataFrame({"Amt": ["100", "100.0", "100.00", "7"], "Code": ["a", "a ", " a", "b"]})
    p = profile_both(tmp_path, frame)
    assert p.column("Amt").kind == Kind.NUMERIC and p.column("Amt").distinct_count == 2
    assert p.column("Code").kind == Kind.STRING and p.column("Code").distinct_count == 2


def test_unique_column_is_detected(tmp_path):
    frame = pd.DataFrame({"ID": [1, 2, 3], "Dup": [1, 1, 2]})
    p = profile_both(tmp_path, frame)
    assert p.column("ID").is_unique and not p.column("Dup").is_unique


def test_kinds_and_extremes(tmp_path):
    frame = pd.DataFrame({"N": [3, 1, 2], "D": ["2024-01-15", "2024-03-01", "2024-02-10"], "S": ["a", "b", "c"]})
    p = profile_both(tmp_path, frame)
    assert [p.column(c).kind for c in "NDS"] == [Kind.NUMERIC, Kind.DATE, Kind.STRING]
    assert (float(p.column("N").min), float(p.column("N").max)) == (1.0, 3.0)
    assert p.column("D").min.startswith("2024-01-15") and p.column("D").max.startswith("2024-03-01")
    assert p.column("S").min is None


def test_numbers_stored_as_text_are_numeric(tmp_path):
    frame = pd.DataFrame({"Amt": ["10", " 20 ", "30.5"]})
    col = profile_both(tmp_path, frame).column("Amt")
    assert col.kind == Kind.NUMERIC and col.nonconforming_count == 0


def test_mixed_column_is_a_string_with_nothing_nonconforming(tmp_path):
    frame = pd.DataFrame({"V": ["10", "20", "n/a"]})
    col = profile_both(tmp_path, frame).column("V")
    assert col.kind == Kind.STRING and col.nonconforming_count == 0


def test_late_bad_values_are_found_beyond_the_inference_sample(tmp_path):
    # The first 1,000 rows are numeric so the kind is NUMERIC; the bad values only exist further down.
    # (the blank is not last: Excel drops trailing empty rows, which would make the formats differ)
    values = [str(i) for i in range(1500)] + ["N/A", "", "n/a", "1500"]
    col = profile_both(tmp_path, pd.DataFrame({"V": values})).column("V")
    assert col.kind == Kind.NUMERIC
    assert col.nonconforming_count == 2     # "N/A" and "n/a" are kept as text; the blank is a null, not a violation
    assert col.null_count == 1


def test_empty_table(tmp_path):
    frame = pd.DataFrame({"A": pd.Series([], dtype="object"), "B": pd.Series([], dtype="object")})
    p = profile_file(write(tmp_path, frame, "csv"))
    assert p.row_count == 0
    assert all(c.null_pct == 0.0 and c.distinct_count == 0 for c in p.columns)


def test_all_null_column(tmp_path):
    frame = pd.DataFrame({"A": [np.nan, np.nan], "B": [1, 2]})
    col = profile_both(tmp_path, frame).column("A")
    assert (col.null_pct, col.distinct_count, col.kind) == (100.0, 0, Kind.STRING)


def test_profile_round_trips_through_json(tmp_path):
    p = profile_file(write(tmp_path, pd.DataFrame({"A": [1, 2], "B": ["x", None]}), "csv"))
    assert type(p).from_json(p.to_json()) == p


def test_unknown_column_lists_the_available_ones(tmp_path):
    p = profile_file(write(tmp_path, pd.DataFrame({"A": [1]}), "csv"))
    with pytest.raises(ValueError, match="Available"):
        p.column("Nope")
