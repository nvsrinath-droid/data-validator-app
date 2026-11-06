from typing import Optional

import duckdb
import pandas as pd

from core.normalize import INFERENCE_SAMPLE
from core.results import ComparisonResult
from core.schemas import ValidationConfig

from .sql_builder import DuckDBDialect, SQLComparison, plan_from_samples


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def load_table(conn: duckdb.DuckDBPyConnection, path: str, table: str, raw: bool = False):
    """Load a CSV/Excel file into an in-memory DuckDB table.

    By default DuckDB guesses CSV column types from its first rows (a late "N/A" in a numeric-looking column
    then fails the load) and pandas turns the Excel text "N/A", "NA", "null"... into NULL.

    raw=True loads every value as text and only empty cells as NULL, for both formats. Data quality checks
    use it so a literal "N/A" or a late bad value is reported rather than hidden or fatal; types are then
    inferred from the values with the same Kind rules the comparison engines use.
    """
    if path.lower().endswith((".xls", ".xlsx")):
        # Excel tops out at ~1M rows, so pandas is fine here and avoids needing
        # a network download of a DuckDB extension on every run.
        frame = (pd.read_excel(path, dtype=str, keep_default_na=False, na_values=[""]) if raw
                 else pd.read_excel(path))
        conn.register(f"{table}_df", frame)
        conn.execute(f"CREATE TABLE {table} AS SELECT * FROM {table}_df")
        conn.unregister(f"{table}_df")
    else:
        options = ", all_varchar=true" if raw else ""
        conn.execute(f"CREATE TABLE {table} AS SELECT * FROM read_csv_auto({_sql_literal(path)}{options})")


class DuckDBEngine:
    """
    Executes data validation directly on massive flat files using DuckDB, bypassing
    pandas memory limits. Uses the same SQL as the pushdown engine (see sql_builder).
    """

    def __init__(self, config: ValidationConfig):
        self.config = config

    _load = staticmethod(load_table)

    def compare(self, file1_path: str, file2_path: str, sample_limit: Optional[int] = None) -> ComparisonResult:
        conn = duckdb.connect(database=":memory:")
        try:
            self._load(conn, file1_path, "file1")
            self._load(conn, file2_path, "file2")

            def run(sql: str):
                cur = conn.execute(sql)
                return [d[0] for d in cur.description], cur.fetchall()

            c1, r1 = run(f"SELECT * FROM file1 LIMIT {INFERENCE_SAMPLE}")
            c2, r2 = run(f"SELECT * FROM file2 LIMIT {INFERENCE_SAMPLE}")
            plan = plan_from_samples(self.config, c1, r1, c2, r2)
            return SQLComparison(plan, DuckDBDialect(), "file1", "file2").run(run, sample_limit)
        finally:
            conn.close()
