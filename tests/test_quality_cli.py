"""python main.py <file> --quality / --profile / --suggest-checks, run in process."""
import json
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

import ai.agent as agent_mod
import main as main_mod


@pytest.fixture
def cli(monkeypatch, tmp_path, capsys):
    """cli("data.csv", "--profile") -> (exit_code, stdout). Hermetic: no .env, no provider keys in the environment."""
    monkeypatch.setattr(main_mod, "load_dotenv", lambda: None)
    for var in main_mod.PROVIDER_KEY_VARS.values():
        monkeypatch.delenv(var, raising=False)

    def run(*argv):
        monkeypatch.setattr(sys, "argv", ["main.py", *map(str, argv), "--output", str(tmp_path / "out")])
        code = main_mod.main()
        return code, capsys.readouterr().out
    return run


@pytest.fixture
def orders(tmp_path):
    path = tmp_path / "orders.csv"
    pd.DataFrame({"ID": [1, 2, 3, 3], "Cust": ["C1", "C2", "C9", None], "Amt": [10, 12, 11, 13],
                  "Updated": ["2024-01-15 10:00:00"] * 4}).to_csv(path, index=False)
    return path


def write_checks(tmp_path, checks, name="checks.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"checks": checks}), encoding="utf-8")
    return path


def fake_completion(content, calls):
    def _completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return _completion


def test_profile(cli, orders):
    code, out = cli(orders, "--profile")
    assert code == 0 and "Rows: 4" in out and "Cust" in out


def test_passing_run_exits_zero_and_writes_a_report(cli, orders, tmp_path):
    checks = write_checks(tmp_path, [{"type": "null_rate", "column": "Cust", "max_pct": 50},
                                     {"type": "freshness", "column": "Updated", "max_age": "2h"}])
    code, out = cli(orders, "--quality", checks, "--as-of", "2024-01-15T11:00:00")
    assert code == 0 and "2 checks: 2 passed, 0 warned, 0 inconclusive, 0 failed" in out
    report = json.loads((tmp_path / "out" / "quality_report.json").read_text(encoding="utf-8"))
    assert [r["status"] for r in report["results"]] == ["pass", "pass"]


def test_failing_run_exits_one_and_shows_offending_values(cli, orders, tmp_path):
    checks = write_checks(tmp_path, [{"type": "distinct", "column": "ID", "unique": True},
                                     {"type": "ref_integrity", "column": "Cust", "ref_name": "customers",
                                      "ref_column": "ID"}])
    customers = tmp_path / "customers.csv"
    pd.DataFrame({"ID": ["C1", "C2"]}).to_csv(customers, index=False)
    code, out = cli(orders, "--quality", checks, "--ref", f"customers={customers}")
    assert code == 1 and "[FAIL]" in out and "C9" in out        # the local console may show the offending value


def test_warnings_do_not_fail_the_run(cli, orders, tmp_path):
    checks = write_checks(tmp_path, [{"type": "null_rate", "column": "Cust", "severity": "warn"}])
    code, out = cli(orders, "--quality", checks)
    assert code == 0 and "[WARN]" in out


def test_check_errors_fail_the_run(cli, orders, tmp_path):
    code, out = cli(orders, "--quality", write_checks(tmp_path, [{"type": "null_rate", "column": "Nope"}]))
    assert code == 1 and "[ERR ]" in out


@pytest.mark.parametrize("checks", [
    [{"type": "run_sql", "column": "ID"}],
    [{"type": "null_rate", "column": "ID", "sql": "DROP TABLE t"}],
])
def test_invalid_check_files_are_usage_errors(cli, orders, tmp_path, checks):
    code, out = cli(orders, "--quality", write_checks(tmp_path, checks))
    assert code == 2 and "Configuration error" in out


def test_missing_files_and_bad_arguments_exit_two(cli, orders, tmp_path):
    assert cli(tmp_path / "nope.csv", "--profile")[0] == 2
    assert cli(orders, "--quality", tmp_path / "nope.json")[0] == 2
    checks = write_checks(tmp_path, [])
    assert cli(orders, "--quality", checks, "--ref", "missing-equals")[0] == 2
    assert cli(orders, "--quality", checks, "--as-of", "not a date")[0] == 2


def test_baseline_round_trip_detects_type_drift(cli, orders, tmp_path):
    baseline = tmp_path / "elsewhere" / "orders.baseline.json"
    drift_check = write_checks(tmp_path, [{"type": "type_drift", "column": "Amt"}])
    assert cli(orders, "--quality", drift_check, "--baseline", baseline)[0] == 2    # no baseline yet: usage error

    ok_checks = write_checks(tmp_path, [{"type": "null_rate", "column": "Amt", "max_pct": 100}], name="ok.json")
    assert cli(orders, "--quality", ok_checks, "--save-baseline", baseline)[0] == 0
    assert baseline.exists()

    drifted = tmp_path / "drifted.csv"
    pd.DataFrame({"ID": [1, 2], "Cust": ["C1", "C2"], "Amt": ["10", "twelve"], "Updated": ["2024-01-15"] * 2}
                 ).to_csv(drifted, index=False)
    code, out = cli(drifted, "--quality", drift_check, "--baseline", baseline)
    assert code == 1 and "[FAIL]" in out and "changed type: numeric -> string" in out


def test_suggest_checks_prints_validated_json_and_sends_no_rows(cli, orders, monkeypatch):
    calls = []
    suggestion = json.dumps({"checks": [{"type": "null_rate", "column": "Cust", "max_pct": 30},
                                        {"type": "null_rate", "column": "Invented"}]})
    monkeypatch.setattr(agent_mod, "completion", fake_completion(suggestion, calls))
    code, out = cli(orders, "--suggest-checks", "--api-key", "k", "--model", "openai/gpt-5")
    assert code == 0 and "Dropped null_rate on unknown column 'Invented'" in out
    printed = json.loads(out[out.index("{"):])
    assert [c["column"] for c in printed["checks"]] == ["Cust"]
    sent = json.dumps(calls[0]["messages"])
    assert "C9" not in sent and "C2" not in sent


def test_suggest_checks_without_a_key_exits_two(cli, orders):
    code, out = cli(orders, "--suggest-checks")
    assert code == 2 and "No API key" in out


def test_explain_prints_the_models_answer(cli, orders, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(agent_mod, "completion", fake_completion("Duplicate IDs; check the extract.", calls))
    checks = write_checks(tmp_path, [{"type": "distinct", "column": "ID", "unique": True}])
    code, out = cli(orders, "--quality", checks, "--explain", "--api-key", "k", "--model", "openai/gpt-5")
    assert code == 1 and "Duplicate IDs; check the extract." in out
    assert "C9" not in json.dumps(calls[0]["messages"])


def test_reconcile_mode_still_requires_a_target(cli, orders):
    with pytest.raises(SystemExit) as exc:
        cli(orders)
    assert exc.value.code == 2


# ---- a good baseline must not be overwritten by accident (review finding #13) -----------------

def drifted_file(tmp_path):
    path = tmp_path / "drifted.csv"
    pd.DataFrame({"ID": [1, 2], "Cust": ["C1", "C2"], "Amt": ["10", "twelve"], "Updated": ["2024-01-15"] * 2}
                 ).to_csv(path, index=False)
    return path


def test_new_baseline_is_saved_even_from_a_failing_run(cli, orders, tmp_path):
    baseline = tmp_path / "b" / "orders.baseline.json"
    checks = write_checks(tmp_path, [{"type": "distinct", "column": "ID", "unique": True}])      # fails: ID 3 repeats
    code, out = cli(orders, "--quality", checks, "--save-baseline", baseline)
    assert code == 1 and baseline.exists() and "Saved baseline" in out


def test_save_baseline_refuses_to_replace_an_existing_file(cli, orders, tmp_path):
    baseline = tmp_path / "orders.baseline.json"
    checks = write_checks(tmp_path, [{"type": "null_rate", "column": "Amt"}])
    assert cli(orders, "--quality", checks, "--save-baseline", baseline)[0] == 0
    before = baseline.read_bytes()
    code, out = cli(drifted_file(tmp_path), "--quality", checks, "--save-baseline", baseline)
    assert code == 2 and "Refusing to overwrite" in out and baseline.read_bytes() == before


def test_same_path_for_baseline_and_save_baseline_cannot_replace_a_good_baseline(cli, orders, tmp_path):
    """The review repro: comparing against a baseline and saving to it in one run replaced it with the drifted profile."""
    baseline = tmp_path / "orders.baseline.json"
    ok = write_checks(tmp_path, [{"type": "null_rate", "column": "Amt"}], name="ok.json")
    assert cli(orders, "--quality", ok, "--save-baseline", baseline)[0] == 0
    before = baseline.read_bytes()
    drift = write_checks(tmp_path, [{"type": "type_drift", "column": "Amt"}], name="drift.json")
    code, _ = cli(drifted_file(tmp_path), "--quality", drift, "--baseline", baseline, "--save-baseline", baseline)
    assert code == 2 and baseline.read_bytes() == before


def test_overwrite_keeps_the_baseline_when_checks_fail(cli, orders, tmp_path):
    baseline = tmp_path / "orders.baseline.json"
    ok = write_checks(tmp_path, [{"type": "null_rate", "column": "Amt"}], name="ok.json")
    assert cli(orders, "--quality", ok, "--save-baseline", baseline)[0] == 0
    before = baseline.read_bytes()
    drift = write_checks(tmp_path, [{"type": "type_drift", "column": "Amt"}], name="drift.json")
    code, out = cli(drifted_file(tmp_path), "--quality", drift, "--baseline", baseline,
                    "--save-baseline", baseline, "--overwrite-baseline")
    assert code == 1 and "Kept the existing baseline" in out and baseline.read_bytes() == before


def test_overwrite_replaces_the_baseline_after_a_passing_run(cli, orders, tmp_path):
    baseline = tmp_path / "orders.baseline.json"
    ok = write_checks(tmp_path, [{"type": "null_rate", "column": "Amt"}], name="ok.json")
    assert cli(orders, "--quality", ok, "--save-baseline", baseline)[0] == 0
    before = baseline.read_bytes()
    grown = tmp_path / "grown.csv"
    pd.DataFrame({"ID": range(10), "Cust": ["C1"] * 10, "Amt": range(10), "Updated": ["2024-01-15"] * 10}).to_csv(grown, index=False)
    code, out = cli(grown, "--quality", ok, "--save-baseline", baseline, "--overwrite-baseline")
    assert code == 0 and "Saved baseline" in out and baseline.read_bytes() != before


def test_explain_masks_a_column_name_that_is_not_in_the_table(cli, orders, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(agent_mod, "completion", fake_completion("ok", calls))
    checks = write_checks(tmp_path, [{"type": "null_rate", "column": "Typo_SSN"}], name="typo.json")
    for extra in ([], ["--hide-column-names"]):
        calls.clear()
        code, _ = cli(orders, "--quality", checks, "--explain", "--api-key", "k", "--model", "openai/gpt-5", *extra)
        assert code == 1 and "Typo_SSN" not in json.dumps(calls[0]["messages"])
