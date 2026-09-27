# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project purpose

TrueAlign Data is a Streamlit app that reconciles a source "system of record" against a target dataset
(CSV/Excel files or SQL databases) and reports missing rows, duplicate keys and value mismatches. It is aimed
at ERP data migration/reconciliation work (JD Edwards, Oracle EBS, Oracle Fusion, Snowflake). An LLM (via
LiteLLM) suggests the primary keys and column mappings between two differently-shaped datasets and helps
interpret plain-English validation rules such as "within 0.01" or "ignore case".

## Workflow rules

- Always work on a branch. Never commit directly to `main`.
- Run `pytest` before every commit; do not commit with failing tests.
- Never commit `.env` or `users.db` (API keys and the bcrypt user store). Both are in `.gitignore`.

## Commands

```bash
python -m venv venv && venv\Scripts\activate     # Windows (source venv/bin/activate elsewhere)
pip install -r requirements.txt
streamlit run app.py                             # web UI on http://localhost:8501
python main.py samples/inventory_system.csv samples/vendor_catalog.csv --config samples/inventory_config.json [--engine duckdb]
pytest                                           # full suite
pytest tests/test_file.py::test_name -q          # single test
```

## Architecture

Three comparison engines share one config model (`core/schemas.py`: `ValidationConfig` = primary keys +
`ColumnMap` list of file1_column -> file2_column with an optional plain-English `validation_rule`).
The Streamlit UI picks an engine by "tier":

| Tier (URL `?engine=`) | Engine | Where computation runs |
|---|---|---|
| `standard` | `core/comparator.py` `DataComparator` | pandas, in memory (files or SQL via `connectors/`) |
| `heavy` | `core/engines/duckdb_engine.py` `DuckDBEngine` | DuckDB reads large CSV/Excel files from disk |
| `pushdown` | `core/engines/sql_pushdown.py` `SQLPushdownEngine` | the remote database itself (FULL OUTER JOIN of two queries) |

The core invariant: **all three engines must produce the same answer for the same data and config**
(NULL handling, numeric/string/date normalization, tolerance rules, duplicate keys, missing rows).
`tests/test_correctness.py` runs every scenario through all three engines (`run_all`); add new semantics there.

How the engines share semantics:
- `core/plan.py` `build_plan()` resolves a config against the real columns into key/column pairs, each with a
  `Kind` (`core/normalize.py`: numeric / date / string, inferred from a sample) and a `RuleSpec`
  (`core/rules.py`). Every engine builds its plan this way, so they agree on what is compared and how.
- The pandas engine renders the plan with pandas; DuckDB and pushdown share `core/engines/sql_builder.py`,
  which renders it as SQL per `Dialect` (null-safe equality, casts and row limits differ per database).
  Only counts and a capped sample of exceptions leave the database.
- Every engine returns `core/results.py` `ComparisonResult`.
- Rules are data, never code: plain-English rules are parsed into a `RuleSpec`; the LLM may only return
  a `RuleSpec` JSON object (validated, extra fields rejected). Do not reintroduce exec/eval.

Other pieces:
- `core/sources.py`: one adapter per tier (`ConnectorPair`, `FilePair`, `PushdownPair`) with
  columns/sample/run; used by both the UI and `main.py`.
- `ui/`: `app.py` only routes. `ui/components.py` holds the shared connection form and the
  map -> run -> results workflow; `ui/pages/*.py` only collect each tier's inputs.
- `ai/agent.py` `AIAgent` wraps LiteLLM. API keys are per user (Streamlit session state) and are passed
  to each `completion()` call; never write them to `os.environ`.
- `core/db.py` builds connection URLs with `URL.create()` (special-character passwords, masked in errors).
- `core/auth.py` is a local SQLite + bcrypt user store (`users.db`); guests cannot load/save templates.
- Mapping templates (`core/templates.py`) are Excel/CSV with columns `File 1 Column`, `File 2 Column`,
  `Validation Rule (Optional)`, `Is Primary Key`.
- `samples/` has demo CSVs, a SQLite db and the scripts that generate them.
