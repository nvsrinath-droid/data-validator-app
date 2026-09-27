"""Section A correctness bugs. Every scenario runs through all three engines, which must agree."""
import numpy as np
import pandas as pd
import pytest

from conftest import ENGINES, config, summary


def run_all(run, source, target, cfg, key_cols, **kw):
    results = {e: run(e, source, target, cfg, **kw) for e in ENGINES}
    views = {e: summary(r, key_cols) for e, r in results.items()}
    for e in ENGINES[1:]:
        assert views[e] == views["pandas"], f"{e} disagrees with pandas"
    return results["pandas"], views["pandas"]


# ---- NULL handling ---------------------------------------------------------------------

@pytest.mark.parametrize("engine", ENGINES)
def test_null_vs_null_is_a_match(run, engine):
    src = pd.DataFrame({"ID": [1, 2], "Note": [None, "x"], "Amt": [np.nan, 5.0]})
    tgt = pd.DataFrame({"ID": [1, 2], "Note": [None, "x"], "Amt": [np.nan, 5.0]})
    res = run(engine, src, tgt, config(["ID"], ("Note", "Note"), ("Amt", "Amt")))
    assert res.mismatched_rows == 0
    assert res.matched_rows == 2


def test_null_vs_value_is_a_mismatch(run):
    src = pd.DataFrame({"ID": [1, 2], "Note": [None, "x"]})
    tgt = pd.DataFrame({"ID": [1, 2], "Note": ["y", None]})
    _, view = run_all(run, src, tgt, config(["ID"], ("Note", "Note")), ["ID"])
    assert view["mismatched"] == 2


def test_null_vs_null_with_tolerance_rule(run):
    src = pd.DataFrame({"ID": [1, 2], "Amt": [np.nan, 10.0]})
    tgt = pd.DataFrame({"ID": [1, 2], "Amt": [np.nan, np.nan]})
    _, view = run_all(run, src, tgt, config(["ID"], ("Amt", "Amt", "within 1")), ["ID"])
    assert view["mismatch_cells"] == [(("2",), "Amt")]


# ---- Type-aware normalization -----------------------------------------------------------

def test_numeric_compare_100_vs_100_00(run):
    src = pd.DataFrame({"ID": [1, 2, 3], "Amt": [100, 250, 7]})
    tgt = pd.DataFrame({"ID": [1, 2, 3], "Amt": ["100.00", "250.0", "7.5"]})
    _, view = run_all(run, src, tgt, config(["ID"], ("Amt", "Amt")), ["ID"])
    assert view["mismatch_cells"] == [(("3",), "Amt")]


def test_strings_are_trimmed_jde_char_padding(run):
    src = pd.DataFrame({"AN8": ["1001", "1002"], "ALPH": ["ACME CORP      ", "  GLOBEX"]})
    tgt = pd.DataFrame({"AN8": ["1001", "1002"], "ALPH": ["ACME CORP", "GLOBEX"]})
    _, view = run_all(run, src, tgt, config(["AN8"], ("ALPH", "ALPH")), ["AN8"])
    assert view["mismatched"] == 0 and view["matched"] == 2


def test_padded_keys_still_join(run):
    src = pd.DataFrame({"CODE": ["AB   ", "CD   "], "V": ["x", "y"]})
    tgt = pd.DataFrame({"CODE": ["AB", "CD"], "V": ["x", "z"]})
    _, view = run_all(run, src, tgt, config(["CODE"], ("V", "V")), ["CODE"])
    assert view["missing_in_target"] == view["missing_in_source"] == 0
    assert view["mismatch_cells"] == [(("CD",), "V")]


def test_trim_can_be_disabled(run):
    src = pd.DataFrame({"ID": [1], "N": ["A  "]})
    tgt = pd.DataFrame({"ID": [1], "N": ["A"]})
    _, view = run_all(run, src, tgt, config(["ID"], ("N", "N"), trim_strings=False), ["ID"])
    assert view["mismatched"] == 1


def test_blank_equals_null_by_default(run):
    src = pd.DataFrame({"ID": [1], "N": ["   "]})
    tgt = pd.DataFrame({"ID": [1], "N": [None]})
    _, view = run_all(run, src, tgt, config(["ID"], ("N", "N")), ["ID"])
    assert view["mismatched"] == 0


def test_dates_compare_as_timestamps(run):
    src = pd.DataFrame({"ID": [1, 2, 3], "D": ["2024-01-15", "2024-02-01", "2024-03-01"]})
    tgt = pd.DataFrame({"ID": [1, 2, 3], "D": ["2024-01-15 00:00:00", "2024-02-02", "2024-03-01T00:00:00"]})
    _, view = run_all(run, src, tgt, config(["ID"], ("D", "D")), ["ID"])
    assert view["mismatch_cells"] == [(("2",), "D")]


def test_date_only_rule_ignores_time(run):
    src = pd.DataFrame({"ID": [1, 2], "D": ["2024-01-15 08:00:00", "2024-01-15 08:00:00"]})
    tgt = pd.DataFrame({"ID": [1, 2], "D": ["2024-01-15 17:30:00", "2024-01-16 08:00:00"]})
    _, view = run_all(run, src, tgt, config(["ID"], ("D", "D", "same date, ignore time")), ["ID"])
    assert view["mismatch_cells"] == [(("2",), "D")]


def test_ignore_case_rule(run):
    src = pd.DataFrame({"ID": [1, 2], "S": ["Active", "Closed"]})
    tgt = pd.DataFrame({"ID": [1, 2], "S": ["ACTIVE ", "Open"]})
    _, view = run_all(run, src, tgt, config(["ID"], ("S", "S", "ignore case")), ["ID"])
    assert view["mismatch_cells"] == [(("2",), "S")]


# ---- Tolerance rules --------------------------------------------------------------------

def test_decimal_absolute_tolerance(run):
    src = pd.DataFrame({"ID": [1, 2, 3], "Amt": [100.00, 100.00, -50.00]})
    tgt = pd.DataFrame({"ID": [1, 2, 3], "Amt": [100.01, 100.02, -50.01]})
    _, view = run_all(run, src, tgt, config(["ID"], ("Amt", "Amt", "must be within 0.01")), ["ID"])
    assert view["mismatch_cells"] == [(("2",), "Amt")]


def test_percentage_tolerance_with_negative_amounts(run):
    # credit memos / reversals are negative; 5% of -100 is a band of ±5, not -5
    src = pd.DataFrame({"ID": [1, 2, 3, 4], "Amt": [-100.0, -100.0, 200.0, 200.0]})
    tgt = pd.DataFrame({"ID": [1, 2, 3, 4], "Amt": [-104.0, -106.0, 190.0, 189.0]})
    _, view = run_all(run, src, tgt, config(["ID"], ("Amt", "Amt", "+/- 5%")), ["ID"])
    assert view["mismatch_cells"] == [(("2",), "Amt"), (("4",), "Amt")]


def test_unknown_rule_warns_and_uses_exact(run):
    src = pd.DataFrame({"ID": [1], "Amt": [10.0]})
    tgt = pd.DataFrame({"ID": [1], "Amt": [10.4]})
    _, view = run_all(run, src, tgt, config(["ID"], ("Amt", "Amt", "roughly the same-ish")), ["ID"])
    assert view["mismatched"] == 1
    assert any("not understood" in w for w in view["warnings"])


# ---- Duplicate primary keys --------------------------------------------------------------

def test_duplicate_keys_reported_and_excluded(run):
    src = pd.DataFrame({"ID": [1, 2, 2, 3], "V": ["a", "b", "b2", "c"]})
    tgt = pd.DataFrame({"ID": [1, 2, 3, 3, 3], "V": ["a", "b", "c", "c", "x"]})
    res, view = run_all(run, src, tgt, config(["ID"], ("V", "V")), ["ID"])
    assert view["duplicates"] == 2
    assert view["matched"] == 1 and view["mismatched"] == 0
    assert view["missing_in_target"] == view["missing_in_source"] == 0
    dups = res.duplicate_keys
    assert sorted(zip(dups["Side"], dups["ID"].astype(int), dups["Count"])) == [("Source", 2, 2), ("Target", 3, 3)]
    assert any("duplicated" in w for w in view["warnings"])


# ---- Missing rows ------------------------------------------------------------------------

def test_missing_rows_when_pk_not_in_mappings(run):
    src = pd.DataFrame({"ID": [1, 2, 3], "V": ["a", "b", "c"]})
    tgt = pd.DataFrame({"ID": [2, 3, 4], "V": ["b", "c", "d"]})
    res, view = run_all(run, src, tgt, config(["ID"], ("V", "V")), ["ID"])
    assert view["missing_in_target_keys"] == [("1",)]
    assert view["missing_in_source"] == 1
    assert list(res.missing_in_source["ID"]) == [4]


def test_missing_rows_with_renamed_composite_key(run):
    src = pd.DataFrame({"CO": ["00001", "00001", "00002"], "DOC": [10, 11, 10], "AMT": [1.0, 2.0, 3.0]})
    tgt = pd.DataFrame({"Company": ["00001", "00002", "00002"], "DocNo": [10, 10, 12], "Amount": [1.0, 3.5, 9.0]})
    cfg = config(["CO", "DOC"], ("CO", "Company"), ("DOC", "DocNo"), ("AMT", "Amount"))
    _, view = run_all(run, src, tgt, cfg, ["CO", "DOC"])
    assert view["missing_in_target_keys"] == [("1", "11")]
    assert view["missing_in_source"] == 1
    assert view["mismatch_cells"] == [(("2", "10"), "AMT -> Amount")]


def test_missing_rows_with_nulls_in_value_columns(run):
    # The old engines flagged missing rows by checking File1_<pk> for NULL; a NULL
    # value column must not make a present row look missing.
    src = pd.DataFrame({"ID": [1, 2], "V": [None, None]})
    tgt = pd.DataFrame({"ID": [1], "V": [None]})
    _, view = run_all(run, src, tgt, config(["ID"], ("V", "V")), ["ID"])
    assert view["missing_in_target_keys"] == [("2",)]
    assert view["matched"] == 1


# ---- Config validation --------------------------------------------------------------------

@pytest.mark.parametrize("engine", ENGINES)
def test_requires_a_primary_key(run, engine):
    df = pd.DataFrame({"ID": [1], "V": ["a"]})
    with pytest.raises(ValueError, match="primary key"):
        run(engine, df, df, config([], ("V", "V")))


@pytest.mark.parametrize("engine", ENGINES)
def test_unknown_column_is_a_clear_error(run, engine):
    df = pd.DataFrame({"ID": [1], "V": ["a"]})
    with pytest.raises(ValueError, match="not found"):
        run(engine, df, df, config(["ID"], ("Nope", "V")))
