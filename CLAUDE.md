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

A fourth tier, `quality` (`?engine=quality`, `ui/pages/quality.py`), is not a comparison engine: it profiles and
checks one table with `core/quality/` (DuckDB; checks are closed-set specs in `core/quality/specs.py`). Its UI flow is
upload -> profile -> editable checks grid (`ui/quality_grid.py`, pure functions) -> run -> results/downloads. The UI
omits `ref_integrity` (grid rows are rejected with a pointer to the CLI) and baselines. The AI buttons may only call
`AIAgent.suggest_checks` / `explain_results`, which build prompts from `ai/quality_summary.py` (summaries, never
rows); suggestions load into the grid and never run automatically. `tests/test_quality_ui.py` enforces this.
Server-side file paths (the "Local File Path" boxes and the SQLite "Database File Path" box) are hidden unless `TRUEALIGN_ALLOW_LOCAL_PATHS=1`, and must be
.csv/.xlsx/.xls; `ui/inputs.py` enforces both, so new file inputs should use `path_input`/`resolve_input`. Uploads go through
`UploadStore` (private per-session folder, 0600 files, deleted on replace/clear/tier switch/session end), never
through loose files in the temp dir.
The upload folder is owner-only, which only protects against *other* OS accounts: anything running as the same account as the app
(including other sessions of it) can read it. Don't claim more than that in docs or comments. Error text shown in the UI must not
contain file paths: use `core.db.scrub_paths` on engine/OS errors and keep path-box messages generic.

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
  map -> run -> results workflow; `ui/pages/*.py` only collect each tier's inputs (`ui/inputs.py` resolves uploads/paths for the file tiers).
- `ai/agent.py` `AIAgent` wraps LiteLLM. API keys are per user (Streamlit session state) and are passed
  to each `completion()` call; never write them to `os.environ`.
- `core/db.py` builds connection URLs with `URL.create()` (special-character passwords, masked in errors).
- `core/auth.py` is a local SQLite + bcrypt user store (`users.db`); guests cannot load/save templates.
- Mapping templates (`core/templates.py`) are Excel/CSV with columns `File 1 Column`, `File 2 Column`,
  `Validation Rule (Optional)`, `Is Primary Key`.
- `samples/` has demo CSVs, a SQLite db and the scripts that generate them.
