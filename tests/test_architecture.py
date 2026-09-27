"""Section C: pushdown returns only exceptions, CLI, templates, and the Streamlit app itself."""
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine

from conftest import config
from core.engines.sql_builder import SQLComparison, SQLiteDialect, plan_from_samples
from core.engines.sql_pushdown import SQLPushdownEngine
from core.sources import FilePair, PushdownPair
from core.templates import config_from_grid, config_to_grid, manual_config, read_template, template_bytes

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


@pytest.fixture
def big_db(tmp_path):
    """1,000 matching rows plus 5 mismatches, 3 source-only and 4 target-only rows."""
    n = 1000
    src = pd.DataFrame({"ID": range(n + 3), "Amt": [float(i) for i in range(n + 3)]})
    tgt = pd.DataFrame({"ID": list(range(n)) + [5000, 5001, 5002, 5003], "Amt": [float(i) for i in range(n)] + [0.0] * 4})
    tgt.loc[:4, "Amt"] += 1  # IDs 0-4 mismatch
    engine = create_engine(f"sqlite:///{tmp_path / 'big.db'}")
    src.to_sql("src", engine, index=False)
    tgt.to_sql("tgt", engine, index=False)
    yield engine
    engine.dispose()


def test_pushdown_counts_are_exact_and_detail_is_capped(big_db):
    res = SQLPushdownEngine(config(["ID"], ("Amt", "Amt"))).compare(
        big_db, "SELECT * FROM src", "SELECT * FROM tgt;", sample_limit=2)
    assert (res.matched_rows, res.mismatched_rows) == (995, 5)
    assert (res.missing_in_target_count, res.missing_in_source_count) == (3, 4)
    assert res.mismatches["ID"].nunique() == 2
    assert len(res.missing_in_target) == 2 and len(res.missing_in_source) == 2
    assert res.truncated


def test_pushdown_exception_query_never_returns_matched_rows(big_db):
    cfg = config(["ID"], ("Amt", "Amt"))
    with big_db.connect() as conn:
        def run(sql):
            r = conn.exec_driver_sql(sql)
            return list(r.keys()), [tuple(x) for x in r.fetchall()]
        c, rows = run("SELECT * FROM src LIMIT 1000")
        plan = plan_from_samples(cfg, c, rows, c, rows)
        cmp = SQLComparison(plan, SQLiteDialect(), "(SELECT * FROM src)", "(SELECT * FROM tgt)")
        _, uncapped = run(cmp.exceptions_sql(limit=None))
        _, capped = run(cmp.exceptions_sql(limit=1))
    assert len(uncapped) == 5 + 3 + 4          # exceptions only, none of the 995 matches
    assert sorted(r[0] for r in capped) == ["M", "S", "T"]  # one per category


def test_pushdown_pair_reads_columns_and_samples(big_db):
    pair = PushdownPair(big_db, "SELECT ID, Amt FROM src", "SELECT * FROM tgt")
    assert pair.columns("source") == ["ID", "Amt"]
    assert len(pair.sample("target", 3)) == 3


def test_file_pair_uses_duckdb(tmp_path):
    for name in ("a.csv", "b.csv"):
        pd.DataFrame({"ID": [1, 2], "V": ["x", "y"]}).to_csv(tmp_path / name, index=False)
    pair = FilePair(str(tmp_path / "a.csv"), str(tmp_path / "b.csv"))
    assert pair.columns("source") == ["ID", "V"]
    assert pair.run(config(["ID"], ("V", "V"))).matched_rows == 2


# ---- Templates / mapping grid ---------------------------------------------------------------

def test_template_round_trip_keeps_keys_and_rules(tmp_path):
    cfg = config(["ID"], ("ID", "Emp_Num"), ("Amt", "Annual_Pay", "within 0.01"), ("Name", "Full_Name"))
    path = tmp_path / "tpl.xlsx"
    path.write_bytes(template_bytes(config_to_grid(cfg), cfg.primary_keys))
    loaded = read_template(str(path))
    assert loaded.primary_keys == ["ID"]
    assert [(m.file1_column, m.file2_column, m.validation_rule) for m in loaded.column_mappings] == [
        ("ID", "Emp_Num", None), ("Amt", "Annual_Pay", "within 0.01"), ("Name", "Full_Name", None)]


def test_bad_template_is_rejected(tmp_path):
    path = tmp_path / "bad.csv"
    pd.DataFrame({"a": [1]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match="Invalid template"):
        read_template(str(path))


def test_grid_drops_blank_and_none_rows():
    grid = pd.DataFrame({"File 1 Column": ["A", "B", None, "D"], "File 2 Column": ["A", "", "C", "None"],
                         "Validation Rule (Optional)": [None, "x", "", "nan"]})
    cfg = config_from_grid(grid, ["A"], trim_strings=False)
    assert [m.file1_column for m in cfg.column_mappings] == ["A"]
    assert cfg.column_mappings[0].validation_rule is None and cfg.trim_strings is False


def test_manual_mapping_pairs_by_name_not_position():
    cfg = manual_config(["ID", "Name", "Amount"], ["amount", "id", "Other", "Extra"])
    assert [(m.file1_column, m.file2_column) for m in cfg.column_mappings] == [
        ("ID", "id"), ("Name", ""), ("Amount", "amount")]


# ---- CLI ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("engine", ["pandas", "duckdb"])
def test_cli_runs_with_config(tmp_path, engine):
    proc = subprocess.run(
        [sys.executable, "main.py", str(SAMPLES / "inventory_system.csv"), str(SAMPLES / "vendor_catalog.csv"),
         "--config", str(SAMPLES / "inventory_config.json"), "--engine", engine, "--output", str(tmp_path)],
        cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 1, proc.stdout + proc.stderr  # the sample data has one real mismatch
    assert "Mismatched rows:          1" in proc.stdout
    assert (tmp_path / "validation_report.xlsx").exists()
    assert (tmp_path / "validation_report.json").exists()


# ---- The Streamlit app ------------------------------------------------------------------------

def _app(engine=None):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.session_state["is_guest"] = True
    at.query_params["auth"] = "guest"
    if engine:
        at.query_params["engine"] = engine
    return at


def assert_tier_labels(at, key, tier_word):
    """Run button and results title use the tier's landing-page name (no "Heavy" / "Remote" leftovers)."""
    assert tier_word in at.button(key=f"{key}_run").label
    assert any(tier_word in h.value and "Validation Results" in h.value for h in at.subheader)


def test_app_landing_page_renders():
    at = _app().run()
    assert not at.exception
    assert any("Launch Massive Engine" in b.label for b in at.button)


@pytest.mark.parametrize("engine", ["standard", "heavy", "pushdown"])
def test_each_tier_page_renders(engine):
    at = _app(engine).run()
    assert not at.exception, at.exception


def test_heavy_tier_end_to_end_with_manual_mapping():
    at = _app("heavy").run()
    at.text_input(key="hfile1_0").input(str(SAMPLES / "inventory_system.csv"))
    at.text_input(key="hfile2_0").input(str(SAMPLES / "inventory_system.csv"))
    at.run()
    at.button(key="heavy_manual").click().run()
    at.multiselect(key="heavy_pk_1").select("ProductID").run()
    at.button(key="heavy_run").click().run()
    assert not at.exception and not at.error, [e.value for e in at.error]
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Matched Rows"] == "10" and metrics["Mismatched Rows"] == "0"
    assert_tier_labels(at, "heavy", "Massive")


def test_pushdown_tier_end_to_end_on_sqlite():
    at = _app("pushdown").run()
    at.selectbox(key="db_type_pd").select("SQLite (Local)").run()
    at.text_input(key="sqlite_pd").input(str(SAMPLES / "local_production.db"))
    at.text_area(key="pd_q1").input("SELECT * FROM employees")
    at.text_area(key="pd_q2").input("SELECT emp_id, UPPER(full_name) AS full_name, department, salary, status FROM employees")
    at.run()
    at.button(key="pd_manual").click().run()
    at.multiselect(key="pd_pk_1").select("emp_id").run()
    at.button(key="pd_run").click().run()
    assert not at.exception and not at.error, [e.value for e in at.error]
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Mismatched Rows"] == "5"  # UPPER(full_name) differs on every row
    assert_tier_labels(at, "pd", "Enterprise")


def test_standard_tier_end_to_end_with_sql_sources():
    at = _app("standard").run()
    for side, query in (("src1", "SELECT * FROM employees"),
                        ("src2", "SELECT emp_id, full_name, department, salary * 1.001 AS salary, status FROM employees")):
        at.radio(key=f"{side}_type_0").set_value("SQL Database").run()
        at.selectbox(key=f"db_type_{side}_0").select("SQLite (Local)").run()
        at.text_input(key=f"sqlite_{side}_0").input(str(SAMPLES / "local_production.db"))
        at.text_area(key=f"q_{side}_0").input(query)
        at.run()
    at.button(key="std_manual").click().run()
    at.multiselect(key="std_pk_1").select("emp_id").run()
    at.button(key="std_run").click().run()
    assert not at.exception and not at.error, [e.value for e in at.error]
    assert {m.label: m.value for m in at.metric}["Mismatched Rows"] == "5"
    assert_tier_labels(at, "std", "Standard")


def test_duckdb_reads_excel_without_extensions(tmp_path):
    src, tgt = tmp_path / "a.xlsx", tmp_path / "b.csv"
    pd.DataFrame({"ID": [1, 2], "Amt": [100, 5]}).to_excel(src, index=False)
    pd.DataFrame({"ID": [1, 2], "Amt": ["100.00", "6"]}).to_csv(tgt, index=False)
    res = FilePair(str(src), str(tgt)).run(config(["ID"], ("Amt", "Amt")))
    assert (res.matched_rows, res.mismatched_rows) == (1, 1)


def test_sql_server_form_offers_driver_and_certificate_options():
    at = _app("pushdown").run()
    at.selectbox(key="db_type_pd").select("Microsoft SQL Server").run()
    assert not at.exception
    driver = at.selectbox(key="driver_pd")
    assert driver.options[:2] == ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"]
    assert at.checkbox(key="trust_pd").value is False
