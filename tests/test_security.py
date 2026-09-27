"""Section B security fixes."""
import ast
import os
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy.engine import make_url

import ai.agent as agent_mod
from ai.agent import AIAgent, resolve_rules
from connectors.sql_connector import SQLConnector
from core.db import build_url, redact
from core.engines.sql_builder import dialect_for
from core.rules import RuleKind
from core.schemas import ColumnMap, ValidationConfig

ROOT = Path(__file__).resolve().parents[1]
NASTY_PASSWORD = "p@ss:w/rd#%?&=+ 1"


def fake_completion(content, calls):
    def _completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return _completion


# ---- API keys ------------------------------------------------------------------------------

@pytest.mark.parametrize("model", ["gpt-4o", "gemini/gemini-2.5-flash", "claude-sonnet-5", "groq/llama3-70b-8192"])
def test_api_key_passed_per_call_not_via_environ(monkeypatch, model):
    calls = []
    monkeypatch.setattr(agent_mod, "completion", fake_completion('{"kind": "exact", "tolerance": null}', calls))
    before = dict(os.environ)

    agent = AIAgent(model_name=model, api_key="sk-user-a")
    agent.interpret_rule("whatever", "A", "B")

    assert dict(os.environ) == before
    assert calls[0]["api_key"] == "sk-user-a"
    assert calls[0]["model"] == model


def test_two_users_keys_do_not_leak_between_agents(monkeypatch):
    calls = []
    monkeypatch.setattr(agent_mod, "completion", fake_completion('{"kind": "exact", "tolerance": null}', calls))
    AIAgent("gpt-4o", "key-user-1").interpret_rule("x", "A", "B")
    AIAgent("gpt-4o", "key-user-2").interpret_rule("x", "A", "B")
    assert [c["api_key"] for c in calls] == ["key-user-1", "key-user-2"]


def test_provider_errors_do_not_echo_the_key(monkeypatch):
    def boom(**kwargs):
        raise Exception(f"401 invalid key {kwargs['api_key']}")
    monkeypatch.setattr(agent_mod, "completion", boom)
    with pytest.raises(RuntimeError) as err:
        AIAgent("gpt-4o", "sk-secret-123").interpret_rule("x", "A", "B")
    assert "sk-secret-123" not in str(err.value)


# ---- No execution of LLM output -------------------------------------------------------------

def test_no_exec_or_eval_in_codebase():
    offenders = []
    for path in ROOT.rglob("*.py"):
        if any(part in ("venv", ".venv", "tests") for part in path.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("exec", "eval", "compile"):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []


def test_ai_rule_becomes_validated_spec(monkeypatch):
    calls = []
    monkeypatch.setattr(agent_mod, "completion", fake_completion(
        '```json\n{"kind": "pct_tolerance", "tolerance": 2.5}\n```', calls))
    spec = AIAgent("gpt-4o", "k").interpret_rule("no more than two and a half percent off", "Amt", "Amount")
    assert spec.kind == RuleKind.PCT_TOLERANCE and spec.tolerance == 2.5


@pytest.mark.parametrize("llm_output", [
    "def evaluate_rules(row):\n    import os; os.system('rm -rf /')",       # code, not JSON
    '{"kind": "python", "code": "__import__(\'os\').system(\'id\')"}',        # unknown kind
    '{"kind": "exact", "tolerance": null, "sql": "1=1; DROP TABLE x"}',       # extra field
    '{"kind": "abs_tolerance", "tolerance": "1 OR 1=1"}',                     # non-numeric tolerance
    '{"kind": "abs_tolerance", "tolerance": -5}',                             # negative tolerance
    '{"kind": "unsupported", "tolerance": null}',
])
def test_malicious_or_invalid_ai_output_is_rejected(monkeypatch, llm_output):
    monkeypatch.setattr(agent_mod, "completion", fake_completion(llm_output, []))
    cfg = ValidationConfig(primary_keys=["ID"], column_mappings=[
        ColumnMap(file1_column="Amt", file2_column="Amt", validation_rule="approximately right")])

    resolved, notes = resolve_rules(cfg, AIAgent("gpt-4o", "k"))

    assert resolved.column_mappings[0].rule_spec is None  # engines fall back to exact + warning
    assert "could not interpret" in notes[0]


def test_resolve_rules_skips_rules_the_parser_understands(monkeypatch):
    calls = []
    monkeypatch.setattr(agent_mod, "completion", fake_completion("{}", calls))
    cfg = ValidationConfig(primary_keys=["ID"], column_mappings=[
        ColumnMap(file1_column="Amt", file2_column="Amt", validation_rule="within 0.01")])
    resolve_rules(cfg, AIAgent("gpt-4o", "k"))
    assert calls == []


def test_ai_suggested_config_cannot_inject_rule_specs(monkeypatch):
    monkeypatch.setattr(agent_mod, "completion", fake_completion(
        '{"primary_keys": ["ID"], "column_mappings": [{"file1_column": "A", "file2_column": "B", '
        '"rule_spec": {"kind": "abs_tolerance", "tolerance": 1e9}}]}', []))
    cfg = AIAgent("gpt-4o", "k").suggest_configuration("ID,A", "ID,B")
    assert cfg.column_mappings[0].rule_spec is None


# ---- Connection URLs -------------------------------------------------------------------------

@pytest.mark.parametrize("db_type, drivername", [
    ("Snowflake", "snowflake"),
    ("Microsoft SQL Server", "mssql+pyodbc"),
    ("Oracle", "oracle+oracledb"),
    ("PostgreSQL", "postgresql+psycopg2"),
])
def test_special_character_passwords_round_trip(db_type, drivername):
    url = build_url(db_type, "db.example.com", "1234", "SALES", "svc_user", NASTY_PASSWORD)
    assert url.drivername == drivername
    assert url.password == NASTY_PASSWORD
    # the rendered string is correctly escaped: parsing it back gives the same credentials
    reparsed = make_url(url.render_as_string(hide_password=False))
    assert reparsed.password == NASTY_PASSWORD
    assert reparsed.username == "svc_user"
    # printing the URL (e.g. in an error) never shows the password
    assert NASTY_PASSWORD not in str(url) and NASTY_PASSWORD not in repr(url)


def test_snowflake_accepts_full_hostname():
    url = build_url("Snowflake", "xy12345.us-east-1.snowflakecomputing.com", "443", "DB/SCHEMA", "u", "p")
    assert url.host == "xy12345.us-east-1"
    assert url.database == "DB/SCHEMA"


def test_oracle_uses_service_name():
    url = build_url("Oracle", "ebs.example.com", "1521", "EBSPROD", "apps", "x")
    assert url.query["service_name"] == "EBSPROD" and url.port == 1521


def test_redact_removes_password_from_errors():
    url = build_url("PostgreSQL", "h", "5432", "d", "u", NASTY_PASSWORD)
    assert NASTY_PASSWORD not in redact(f"could not connect with {NASTY_PASSWORD}", url)


def test_sqlite_url_and_dialect_aware_sampling(tmp_path):
    url = build_url("SQLite (Local)", sqlite_path=str(tmp_path / "x.db"))
    pd.DataFrame({"ID": range(10)}).to_sql("t", url.render_as_string(), index=False)
    conn = SQLConnector(url, "SELECT * FROM t;")
    assert len(conn.get_sample_data(3)) == 3
    assert len(conn.read_data()) == 10


@pytest.mark.parametrize("dialect, expected", [
    ("mssql", "SELECT TOP 5 * FROM (SELECT 1) lim"),
    ("oracle", "SELECT * FROM (SELECT 1) lim FETCH FIRST 5 ROWS ONLY"),
    ("snowflake", "SELECT * FROM (SELECT 1) lim LIMIT 5"),
])
def test_row_limit_syntax_per_dialect(dialect, expected):
    assert dialect_for(dialect).limit("SELECT 1", 5) == expected


# ---- .gitignore -------------------------------------------------------------------------------

def test_gitignore_is_utf8_and_covers_secrets():
    raw = (ROOT / ".gitignore").read_bytes()
    assert b"\x00" not in raw  # the old file had a UTF-16 line
    lines = {line.strip() for line in raw.decode("utf-8").splitlines()}
    assert {".env", "users.db", "output/"} <= lines
