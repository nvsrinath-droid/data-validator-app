"""Single-table column profiling in DuckDB.

Everything is computed with the same Kind inference and SQL normalization the reconciliation
engines use (core.normalize / sql_builder.normalize_expr), so "null", "number" and "date"
mean the same thing here as in a comparison. Only aggregates are fetched, plus a bounded
sample per column to infer its kind.
"""
import json
from typing import List, Optional

import duckdb
from pydantic import BaseModel

from core.engines.duckdb_engine import load_table
from core.engines.sql_builder import DuckDBDialect, normalize_expr
from core.normalize import INFERENCE_SAMPLE, Kind, infer_kind

DIALECT = DuckDBDialect()


class ColumnProfile(BaseModel):
    name: str
    db_type: str
    kind: Kind
    non_null_count: int
    null_count: int           # NULL or blank
    null_pct: float           # 0-100
    distinct_count: int       # distinct normalized non-null values
    nonconforming_count: int  # non-blank values that do not parse as `kind` (always 0 for strings)
    min: Optional[str] = None  # numeric/date columns only
    max: Optional[str] = None

    @property
    def is_unique(self) -> bool:
        return self.non_null_count > 0 and self.distinct_count == self.non_null_count


class TableProfile(BaseModel):
    row_count: int
    columns: List[ColumnProfile]

    def column(self, name: str) -> ColumnProfile:
        for c in self.columns:
            if c.name == name:
                return c
        raise ValueError(f"Column {name!r} not found. Available: {[c.name for c in self.columns]}")

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, text: str) -> "TableProfile":
        return cls.model_validate(json.loads(text))


def quote(name: str) -> str:
    return DIALECT.quote(name)


def identity_expr(q: str, kind: Kind) -> str:
    """What makes two non-blank values "the same value" for distinct counts and duplicate detection.

    Values that parse as the column's kind compare by parsed value (100 = 100.0); values that do not parse
    compare by their trimmed text, so unparseable values like 'N/A' are neither dropped nor lumped together.
    (An unparseable text can never equal a formatted parsed value, so the two groups cannot collide.)
    """
    text = normalize_expr(DIALECT, q, Kind.STRING)
    if kind == Kind.STRING:
        return text
    return f"COALESCE(CAST({normalize_expr(DIALECT, q, kind)} AS VARCHAR), {text})"


def column_sample(conn: duckdb.DuckDBPyConnection, table: str, name: str) -> list:
    """Up to INFERENCE_SAMPLE non-null values of a column, used to infer its Kind."""
    q = quote(name)
    return [r[0] for r in conn.execute(
        f"SELECT {q} FROM {table} WHERE {q} IS NOT NULL LIMIT {INFERENCE_SAMPLE}").fetchall()]


def _profile_column(conn: duckdb.DuckDBPyConnection, table: str, name: str, db_type: str, rows: int) -> ColumnProfile:
    q = quote(name)
    kind = infer_kind(column_sample(conn, table, name), [])

    text = normalize_expr(DIALECT, q, Kind.STRING)   # trimmed, blank -> NULL
    value = normalize_expr(DIALECT, q, kind)         # the column's own kind
    nonconforming = (f"SUM(CASE WHEN ({text}) IS NOT NULL AND ({value}) IS NULL THEN 1 ELSE 0 END)"
                     if kind != Kind.STRING else "0")
    extremes = (f"CAST(MIN({value}) AS VARCHAR), CAST(MAX({value}) AS VARCHAR)"
                if kind != Kind.STRING else "NULL, NULL")
    non_null, distinct, bad, lo, hi = conn.execute(
        f"SELECT COUNT({text}), COUNT(DISTINCT {identity_expr(q, kind)}), COALESCE({nonconforming}, 0), {extremes} FROM {table}"
    ).fetchone()
    nulls = rows - non_null
    return ColumnProfile(
        name=name, db_type=db_type, kind=kind, non_null_count=non_null, null_count=nulls,
        null_pct=round(100.0 * nulls / rows, 6) if rows else 0.0,
        distinct_count=distinct, nonconforming_count=int(bad), min=lo, max=hi)


def profile_table(conn: duckdb.DuckDBPyConnection, table: str) -> TableProfile:
    rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    described = conn.execute(f"DESCRIBE {table}").fetchall()
    return TableProfile(row_count=rows, columns=[
        _profile_column(conn, table, d[0], d[1], rows) for d in described])


def profile_file(path: str) -> TableProfile:
    """Profile a CSV/Excel file without leaving DuckDB."""
    conn = duckdb.connect(database=":memory:")
    try:
        load_table(conn, path, "t", raw=True)
        return profile_table(conn, "t")
    finally:
        conn.close()
