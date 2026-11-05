from typing import Optional

import duckdb
import pandas as pd

from core.normalize import INFERENCE_SAMPLE
from core.results import ComparisonResult
from core.schemas import ValidationConfig

from .sql_builder import DuckDBDialect, SQLComparison, plan_from_samples


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class DuckDBEngine:
    """
    Executes data validation directly on massive flat files using DuckDB, bypassing
    pandas memory limits. Uses the same SQL as the pushdown engine (see sql_builder).
    """

    def __init__(self, config: ValidationConfig):
        self.config = config

    @staticmethod
    def _load(conn: duckdb.DuckDBPyConnection, path: str, table: str):
        if path.lower().endswith((".xls", ".xlsx")):
            # Excel tops out at ~1M rows, so pandas is fine here and avoids needing
            # a network download of a DuckDB extension on every run.
            frame = pd.read_excel(path)
            conn.register(f"{table}_df", frame)
            conn.execute(f"CREATE TABLE {table} AS SELECT * FROM {table}_df")
            conn.unregister(f"{table}_df")
        else:
            conn.execute(f"CREATE TABLE {table} AS SELECT * FROM read_csv_auto({_sql_literal(path)})")

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
