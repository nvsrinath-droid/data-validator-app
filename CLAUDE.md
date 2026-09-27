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
python main.py file1.csv file2.csv --config config.json   # CLI, pandas engine
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
Any change to comparison semantics must be made in every engine and covered by tests that run the
same fixture through all three.

- `ai/agent.py` `AIAgent` wraps LiteLLM for config suggestion and rule interpretation. API keys are
  per-user (held in Streamlit session state) and must be passed per call, never written to `os.environ`.
- `connectors/` provides `FileConnector` / `SQLConnector` (read full data or a sample) for the pandas engine.
- `core/auth.py` is a local SQLite + bcrypt user store (`users.db`); guests can use the app but cannot
  load/save mapping templates.
- Mapping templates are Excel/CSV files with columns `File 1 Column`, `File 2 Column`,
  `Validation Rule (Optional)`, `Is Primary Key`.
