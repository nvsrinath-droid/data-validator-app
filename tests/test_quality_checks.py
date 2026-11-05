"""Quality checks end to end. Every scenario runs from CSV and from XLSX, which must agree."""
from datetime import datetime, timezone

import pandas as pd
import pytest

from core.normalize import Kind
from core.quality.baseline import compare_profiles, load_baseline, save_baseline
from core.quality.engine import QualityEngine
from core.quality.profile import profile_file
from core.quality.specs import Distinct, Freshness, NullRate, Outliers, RefIntegrity, TypeDrift
from test_quality import FORMATS, write

AS_OF = datetime(2024, 1, 16, 12, 0, 0)


def run_both(tmp_path, frame, checks, refs=None, **kw):
    """Run the checks on CSV and XLSX copies of the data (and references); the results must agree."""
    results = {}
    for fmt in FORMATS:
        paths = {name: write(tmp_path, f, fmt, name=f"ref_{name}") for name, f in (refs or {}).items()}
        results[fmt] = QualityEngine(checks, references=paths, as_of=AS_OF, **kw).run(write(tmp_path, frame, fmt))

    def view(r):
        return [(x.status, None if x.metric is None else round(x.metric, 6), x.violations) for x in r.results]

    assert view(results["xlsx"]) == view(results["csv"]), "xlsx disagrees with csv"
    return results["csv"]


def only(result):
    assert len(result.results) == 1
    return result.results[0]


# ---- null_rate ---------------------------------------------------------------------------

def test_null_rate_boundary_counts_blank_and_padded_blank(tmp_path):
    frame = pd.DataFrame({"A": ["x", None, "  ", "y"]})            # 50% null-or-blank
    assert only(run_both(tmp_path, frame, [NullRate(column="A", max_pct=50)])).status == "pass"
    r = only(run_both(tmp_path, frame, [NullRate(column="A", max_pct=49.9)]))
    assert (r.status, r.metric, r.violations) == ("fail", 50.0, 2)
    assert sorted(r.sample["_row"]) == [2, 3] and len(r.sample) == 2


def test_warn_severity_does_not_fail_the_run(tmp_path):
    res = run_both(tmp_path, pd.DataFrame({"A": [None, 1]}), [NullRate(column="A", severity="warn")])
    assert only(res).status == "warn" and not res.has_failures


# ---- distinct ----------------------------------------------------------------------------

def test_unique_flags_repeats_but_not_nulls(tmp_path):
    frame = pd.DataFrame({"K": ["a", "b", "b", None, None, "c"]})
    r = only(run_both(tmp_path, frame, [Distinct(column="K", unique=True)]))
    assert (r.status, r.violations) == ("fail", 1)               # NULLs are not duplicates of each other
    assert r.sample.to_dict("records") == [{"value": "b", "rows": 2}]


def test_unique_uses_numeric_equality(tmp_path):
    r = only(run_both(tmp_path, pd.DataFrame({"K": ["100", "100.0", "7"]}), [Distinct(column="K", unique=True)]))
    assert r.status == "fail" and r.violations == 1


def test_distinct_bounds(tmp_path):
    frame = pd.DataFrame({"Status": ["A", "B", "A", "C"]})
    assert only(run_both(tmp_path, frame, [Distinct(column="Status", min_distinct=2, max_distinct=3)])).status == "pass"
    assert only(run_both(tmp_path, frame, [Distinct(column="Status", max_distinct=2)])).status == "fail"
    assert only(run_both(tmp_path, frame, [Distinct(column="Status", min_distinct=4)])).status == "fail"


# ---- type drift --------------------------------------------------------------------------

def test_type_drift_finds_bad_values_past_the_inference_sample(tmp_path):
    values = [str(i) for i in range(1200)] + ["N/A", "12O", "7"]       # letter O in "12O"
    r = only(run_both(tmp_path, pd.DataFrame({"V": values}), [TypeDrift(column="V", expected=Kind.NUMERIC)]))
    assert (r.status, r.violations) == ("fail", 2)
    assert sorted(r.sample["value"]) == ["12O", "N/A"]


def test_type_drift_tolerance_percent(tmp_path):
    frame = pd.DataFrame({"V": ["1", "2", "3", "x"]})                  # 25% bad
    assert only(run_both(tmp_path, frame, [TypeDrift(column="V", expected=Kind.NUMERIC, max_pct=25)])).status == "pass"
    assert only(run_both(tmp_path, frame, [TypeDrift(column="V", expected=Kind.NUMERIC, max_pct=24)])).status == "fail"


def test_type_drift_dates_and_strings(tmp_path):
    frame = pd.DataFrame({"D": ["2024-01-15", "15/01/2024", "2024-02-01"]})
    assert only(run_both(tmp_path, frame, [TypeDrift(column="D", expected=Kind.DATE)])).violations == 1
    assert only(run_both(tmp_path, frame, [TypeDrift(column="D", expected=Kind.STRING)])).status == "pass"


def test_type_drift_takes_the_type_from_a_baseline(tmp_path):
    good = profile_file(write(tmp_path, pd.DataFrame({"V": [1, 2, 3]}), "csv", name="good"))
    path = write(tmp_path, pd.DataFrame({"V": ["1", "two", "3"]}), "csv")
    r = only(QualityEngine([TypeDrift(column="V")], baseline=good, as_of=AS_OF).run(path))
    assert (r.status, r.violations) == ("fail", 1)


def test_type_drift_without_expected_or_baseline_is_an_error(tmp_path):
    r = only(run_both(tmp_path, pd.DataFrame({"V": [1]}), [TypeDrift(column="V")]))
    assert r.status == "error" and "baseline" in r.message


def test_baseline_reports_schema_and_null_drift(tmp_path):
    before = profile_file(write(tmp_path, pd.DataFrame(
        {"A": [1, 2, 3, 4], "B": ["x", "y", "z", "w"], "C": [1, 2, 3, 4]}), "csv", name="before"))
    after = profile_file(write(tmp_path, pd.DataFrame(
        {"A": ["1", "2", "q", "4"], "B": ["x", None, None, "w"], "D": [1, 2, 3, 4]}), "csv", name="after"))
    findings = " ".join(compare_profiles(before, after))
    assert "'C' was in the baseline but is missing" in findings
    assert "'D' is new" in findings
    assert "'A' changed type: numeric -> string" in findings
    assert "'B' null rate rose from 0.0% to 50.0%" in findings


def test_baseline_survives_save_and_load(tmp_path):
    p = profile_file(write(tmp_path, pd.DataFrame({"A": [1, 2]}), "csv"))
    path = tmp_path / "nested" / "orders.baseline.json"
    save_baseline(p, str(path))
    assert load_baseline(str(path)) == p


def test_baseline_drift_is_reported_as_run_warnings(tmp_path):
    base = profile_file(write(tmp_path, pd.DataFrame({"A": [1, 2], "B": [1, 2]}), "csv", name="base"))
    res = QualityEngine([], baseline=base).run(write(tmp_path, pd.DataFrame({"A": [1, 2]}), "csv"))
    assert any("'B' was in the baseline" in w for w in res.warnings)


# ---- freshness ---------------------------------------------------------------------------

def test_freshness_stale_and_fresh(tmp_path):
    frame = pd.DataFrame({"Updated": ["2024-01-14", "2024-01-15 08:30:00"]})   # newest is 27.5h before AS_OF
    stale = only(run_both(tmp_path, frame, [Freshness(column="Updated", max_age="24h")]))
    assert stale.status == "fail" and stale.metric == pytest.approx(27.5)
    assert only(run_both(tmp_path, frame, [Freshness(column="Updated", max_age="36h")])).status == "pass"
    assert only(run_both(tmp_path, frame, [Freshness(column="Updated", max_age="2d")])).status == "pass"


def test_freshness_boundary_is_inclusive(tmp_path):
    frame = pd.DataFrame({"Updated": ["2024-01-15 12:00:00"]})                  # exactly 24h
    assert only(run_both(tmp_path, frame, [Freshness(column="Updated", max_age="24h")])).status == "pass"


def test_freshness_with_nothing_parseable_fails(tmp_path):
    r = only(run_both(tmp_path, pd.DataFrame({"Updated": ["soon", None]}), [Freshness(column="Updated")]))
    assert r.status == "fail" and "no parseable dates" in r.message


def test_freshness_future_dates_pass_with_a_note(tmp_path):
    r = only(run_both(tmp_path, pd.DataFrame({"Updated": ["2024-02-01"]}), [Freshness(column="Updated", max_age="1h")]))
    assert r.status == "pass" and "future" in r.message


# ---- referential integrity ---------------------------------------------------------------

def test_orphans_are_reported_and_null_children_ignored(tmp_path):
    orders = pd.DataFrame({"Cust": ["C1", "C2", "C9", "C9", None, "C8"]})
    customers = pd.DataFrame({"ID": ["C1", "C2", "C3"]})
    r = only(run_both(tmp_path, orders, [RefIntegrity(column="Cust", ref_name="cust", ref_column="ID")],
                      refs={"cust": customers}))
    assert (r.status, r.violations) == ("fail", 3)
    assert r.sample.to_dict("records") == [{"value": "C9", "rows": 2}, {"value": "C8", "rows": 1}]


def test_orphan_tolerance(tmp_path):
    orders, customers = pd.DataFrame({"Cust": ["C1", "C9"]}), pd.DataFrame({"ID": ["C1"]})
    check = RefIntegrity(column="Cust", ref_name="cust", ref_column="ID", max_orphans=1)
    assert only(run_both(tmp_path, orders, [check], refs={"cust": customers})).status == "pass"


def test_padded_keys_and_null_parents_do_not_cause_false_orphans(tmp_path):
    orders = pd.DataFrame({"Code": ["AB   ", "CD"]})
    parents = pd.DataFrame({"Code": ["AB", None, "CD  "]})                        # a NULL parent must not hide orphans
    check = RefIntegrity(column="Code", ref_name="p", ref_column="Code")
    assert only(run_both(tmp_path, orders, [check], refs={"p": parents})).status == "pass"
    orders2 = pd.DataFrame({"Code": ["AB", "ZZ"]})
    assert only(run_both(tmp_path, orders2, [check], refs={"p": parents})).violations == 1


def test_numeric_child_matches_text_parent(tmp_path):
    orders = pd.DataFrame({"Cust": [100, 200, 300]})
    parents = pd.DataFrame({"ID": ["100", "200.0"]})
    r = only(run_both(tmp_path, orders, [RefIntegrity(column="Cust", ref_name="p", ref_column="ID")], refs={"p": parents}))
    assert r.violations == 1 and r.sample.iloc[0]["value"] in ("300", "300.0")


def test_bad_references_are_errors_not_crashes(tmp_path):
    frame = pd.DataFrame({"Cust": ["C1"]})
    unknown = only(run_both(tmp_path, frame, [RefIntegrity(column="Cust", ref_name="nope", ref_column="ID")]))
    assert unknown.status == "error" and "Unknown reference" in unknown.message
    missing_col = only(run_both(tmp_path, frame, [RefIntegrity(column="Cust", ref_name="p", ref_column="Zzz")],
                                refs={"p": pd.DataFrame({"ID": ["C1"]})}))
    assert missing_col.status == "error" and "Available" in missing_col.message


# ---- outliers ----------------------------------------------------------------------------

def test_iqr_outliers_and_worst_first_sample(tmp_path):
    frame = pd.DataFrame({"Amt": [10, 11, 12, 13, 14, 15, 16, 17, 500, -300]})
    r = only(run_both(tmp_path, frame, [Outliers(column="Amt")]))
    assert (r.status, r.violations) == ("fail", 2)
    assert sorted(float(v) for v in r.sample["value"]) == [-300, 500]
    assert only(run_both(tmp_path, frame, [Outliers(column="Amt", max_count=2)])).status == "pass"


def test_constant_column_has_no_outliers(tmp_path):
    for method in ("iqr", "zscore"):
        r = only(run_both(tmp_path, pd.DataFrame({"Amt": [5] * 20}), [Outliers(column="Amt", method=method)]))
        assert (r.status, r.violations) == ("pass", 0)


def test_iqr_with_tied_values_flags_the_lone_extreme(tmp_path):
    r = only(run_both(tmp_path, pd.DataFrame({"Amt": [1, 1, 1, 1, 100]}), [Outliers(column="Amt")]))
    assert r.violations == 1


def test_zscore_outliers(tmp_path):
    frame = pd.DataFrame({"Amt": [10.0 + (i % 5) for i in range(40)] + [1000.0]})
    r = only(run_both(tmp_path, frame, [Outliers(column="Amt", method="zscore")]))
    assert (r.status, r.violations) == ("fail", 1)


def test_outliers_ignore_nulls_and_need_a_numeric_column(tmp_path):
    frame = pd.DataFrame({"Amt": [1, 2, 3, None, 2, 1, 3], "Name": list("abcdefg")})
    assert only(run_both(tmp_path, frame, [Outliers(column="Amt")])).status == "pass"
    r = only(run_both(tmp_path, frame, [Outliers(column="Name")]))
    assert r.status == "error" and "numeric" in r.message


# ---- whole-run behaviour -------------------------------------------------------------------

def test_empty_table(tmp_path):
    frame = pd.DataFrame({"A": pd.Series([], dtype="object"), "D": pd.Series([], dtype="object")})
    checks = [NullRate(column="A"), Distinct(column="A", unique=True), Outliers(column="D"),
              TypeDrift(column="A", expected=Kind.NUMERIC), Freshness(column="D")]
    res = QualityEngine(checks, as_of=AS_OF).run(write(tmp_path, frame, "csv"))
    # Outliers on an empty (string-kind) column is a configuration error; freshness has no dates to find.
    assert [r.status for r in res.results] == ["pass", "pass", "error", "pass", "fail"]
    assert res.row_count == 0


def test_unknown_column_is_an_error_result_and_other_checks_still_run(tmp_path):
    res = run_both(tmp_path, pd.DataFrame({"A": [None, 1]}), [NullRate(column="Missing"), NullRate(column="A", max_pct=50)])
    assert [r.status for r in res.results] == ["error", "pass"]
    assert "Available" in res.results[0].message and res.has_failures


def test_samples_are_capped(tmp_path):
    frame = pd.DataFrame({"A": [None] * 100, "B": range(100)})
    r = only(QualityEngine([NullRate(column="A")], sample_limit=5).run(write(tmp_path, frame, "csv")))
    assert r.violations == 100 and len(r.sample) == 5
    assert list(r.sample.columns) == ["_row", "value"]          # only the checked column, never the whole row


def test_aware_as_of_is_rejected():
    with pytest.raises(ValueError, match="naive"):
        QualityEngine([], as_of=datetime(2024, 1, 1, tzinfo=timezone.utc))
