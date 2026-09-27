"""SQL generation shared by the DuckDB and SQL pushdown engines.

Both engines express the comparison as SQL so the heavy lifting (normalizing,
joining, comparing, counting) runs where the data lives. Only aggregate counts
and a capped sample of exceptions ever leave the database.

Query shape (CTEs):
  src / tgt      normalized keys (k*), normalized values (n*), raw values (rk*, r*), presence flag p
  src_d / tgt_d  keys that occur more than once on that side
  dk             union of duplicated keys; excluded from the join on both sides
  j              FULL OUTER JOIN on null-safe key equality, one mismatch flag x* per column
  j2             j plus xm = 1 when any column mismatches
"""
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

import pandas as pd

from core.comparator import remark, rule_label
from core.normalize import INFERENCE_SAMPLE, Kind
from core.plan import ColumnPlan, ComparisonPlan, build_plan
from core.results import MISMATCH_COLUMNS, ComparisonResult
from core.rules import FLOAT_EPSILON, RuleKind
from core.schemas import ValidationConfig

Rows = List[Tuple]
# Executes SQL, returns (column_names, rows)
RunFn = Callable[[str], Tuple[List[str], Rows]]


class Dialect:
    """ANSI / PostgreSQL flavoured defaults; subclasses override what differs."""
    name = "ansi"

    def __init__(self, quote: Optional[Callable[[str], str]] = None):
        self._quote = quote

    def quote(self, ident: str) -> str:
        if self._quote:
            return self._quote(ident)
        return '"' + ident.replace('"', '""') + '"'

    def to_str(self, e: str) -> str:
        return f"CAST({e} AS VARCHAR)"

    def to_num(self, e: str) -> str:
        return f"CAST({e} AS DOUBLE PRECISION)"

    def to_ts(self, e: str) -> str:
        return f"CAST({e} AS TIMESTAMP)"

    def ts_to_date(self, e: str) -> str:
        return f"CAST({e} AS DATE)"

    def null_safe_eq(self, a: str, b: str) -> str:
        return f"({a} IS NOT DISTINCT FROM {b})"

    def limit(self, sql: str, n: int) -> str:
        return f"SELECT * FROM ({sql}) lim LIMIT {int(n)}"


class DuckDBDialect(Dialect):
    name = "duckdb"

    def to_num(self, e):
        return f"TRY_CAST(TRIM(CAST({e} AS VARCHAR)) AS DOUBLE)"

    def to_ts(self, e):
        return f"TRY_CAST(TRIM(CAST({e} AS VARCHAR)) AS TIMESTAMP)"


class SQLiteDialect(Dialect):
    name = "sqlite"

    def to_str(self, e):
        return f"CAST({e} AS TEXT)"

    def to_num(self, e):
        # SQLite's CAST('abc' AS REAL) is 0.0, not NULL; only cast things that look numeric.
        t = f"TRIM(CAST({e} AS TEXT))"
        return (f"(CASE WHEN typeof({e}) IN ('integer', 'real') THEN CAST({e} AS REAL) "
                f"WHEN {t} GLOB '*[0-9]*' AND {t} NOT GLOB '*[^0-9.eE+-]*' THEN CAST({t} AS REAL) END)")

    def to_ts(self, e):
        return f"datetime(TRIM(CAST({e} AS TEXT)))"

    def ts_to_date(self, e):
        return f"date({e})"

    def null_safe_eq(self, a, b):
        return f"({a} IS {b})"


class SnowflakeDialect(Dialect):
    name = "snowflake"

    def to_num(self, e):
        return f"CAST({e} AS DOUBLE)"

    def to_ts(self, e):
        return f"CAST({e} AS TIMESTAMP_NTZ)"


class OracleDialect(Dialect):
    name = "oracle"

    def to_str(self, e):
        return f"TO_CHAR({e})"

    def to_num(self, e):
        return f"CAST({e} AS BINARY_DOUBLE)"

    def ts_to_date(self, e):
        return f"TRUNC({e})"

    def null_safe_eq(self, a, b):
        return f"(DECODE({a}, {b}, 1, 0) = 1)"  # DECODE treats NULL = NULL

    def limit(self, sql, n):
        return f"SELECT * FROM ({sql}) lim FETCH FIRST {int(n)} ROWS ONLY"


class MSSQLDialect(Dialect):
    name = "mssql"

    def to_str(self, e):
        return f"CAST({e} AS NVARCHAR(4000))"

    def to_num(self, e):
        return f"TRY_CAST({e} AS FLOAT)"

    def to_ts(self, e):
        return f"TRY_CAST({e} AS DATETIME2)"

    def null_safe_eq(self, a, b):
        return f"({a} = {b} OR ({a} IS NULL AND {b} IS NULL))"

    def limit(self, sql, n):
        return f"SELECT TOP {int(n)} * FROM ({sql}) lim"


DIALECTS = {d.name: d for d in (Dialect, DuckDBDialect, SQLiteDialect, SnowflakeDialect, OracleDialect, MSSQLDialect)}
DIALECTS["postgresql"] = Dialect


def dialect_for(name: str, quote: Optional[Callable[[str], str]] = None) -> Dialect:
    return DIALECTS.get(name, Dialect)(quote)


def clean_query(query: str) -> str:
    return query.strip().rstrip(";").strip()


@dataclass
class SQLComparison:
    """Builds and runs the comparison for one plan against two relations (table names or subqueries)."""
    plan: ComparisonPlan
    dialect: Dialect
    source_rel: str
    target_rel: str

    # ---- expression helpers -------------------------------------------------
    def _norm(self, raw: str, kind: Kind) -> str:
        d = self.dialect
        if kind == Kind.NUMERIC:
            return d.to_num(raw)
        if kind == Kind.DATE:
            return d.to_ts(raw)
        expr = d.to_str(raw)
        if self.plan.trim:
            expr = f"TRIM({expr})"
        if self.plan.blank_as_null:
            expr = f"NULLIF({expr}, '')"
        return expr

    def _match(self, a: str, b: str, col: ColumnPlan) -> str:
        d, spec = self.dialect, col.rule
        if spec.kind == RuleKind.EXACT:
            return d.null_safe_eq(a, b)
        if spec.kind == RuleKind.ABS_TOLERANCE:
            cond = f"ABS({a} - {b}) <= {spec.tolerance + FLOAT_EPSILON!r}"
        elif spec.kind == RuleKind.PCT_TOLERANCE:
            # ABS(source) so negative amounts get a positive tolerance band
            cond = f"ABS({a} - {b}) <= ABS({a}) * {float(spec.tolerance)!r} / 100.0 + {FLOAT_EPSILON!r}"
        elif spec.kind == RuleKind.IGNORE_CASE:
            cond = f"LOWER({a}) = LOWER({b})"
        elif spec.kind == RuleKind.IGNORE_WHITESPACE:
            cond = f"REPLACE({a}, ' ', '') = REPLACE({b}, ' ', '')"
        elif spec.kind == RuleKind.DATE_ONLY:
            cond = f"{d.ts_to_date(a)} = {d.ts_to_date(b)}"
        else:  # pragma: no cover - RuleSpec validation prevents this
            raise ValueError(spec.kind)
        return f"(({a} IS NULL AND {b} IS NULL) OR ({a} IS NOT NULL AND {b} IS NOT NULL AND {cond}))"

    def _keys_eq(self, left: str, right: str) -> str:
        return " AND ".join(self.dialect.null_safe_eq(f"{left}.k{i}", f"{right}.k{i}") for i in range(len(self.plan.keys)))

    # ---- query text -----------------------------------------------------------
    def _side_cte(self, rel: str, side: str) -> str:
        q = self.dialect.quote
        parts = ["1 AS p"]
        for i, k in enumerate(self.plan.keys):
            raw = f"t.{q(k.source if side == 'source' else k.target)}"
            parts += [f"{self._norm(raw, k.kind)} AS k{i}", f"{raw} AS rk{i}"]
        for i, c in enumerate(self.plan.columns):
            raw = f"t.{q(c.source if side == 'source' else c.target)}"
            parts += [f"{self._norm(raw, c.kind)} AS n{i}", f"{raw} AS r{i}"]
        return f"SELECT {', '.join(parts)} FROM {rel} t"

    @property
    def _key_list(self) -> str:
        return ", ".join(f"k{i}" for i in range(len(self.plan.keys)))

    @property
    def j_columns(self) -> List[str]:
        nk, nc = len(self.plan.keys), len(self.plan.columns)
        return (["sp", "tp"] + [f"s_rk{i}" for i in range(nk)] + [f"t_rk{i}" for i in range(nk)]
                + [f"s_r{i}" for i in range(nc)] + [f"t_r{i}" for i in range(nc)]
                + [f"s_k{i}" for i in range(nk)] + [f"x{i}" for i in range(nc)] + ["xm"])

    def ctes(self) -> str:
        nk, nc = len(self.plan.keys), len(self.plan.columns)
        keys = self._key_list
        select = ["s.p AS sp", "t.p AS tp"]
        select += [f"s.rk{i} AS s_rk{i}" for i in range(nk)] + [f"t.rk{i} AS t_rk{i}" for i in range(nk)]
        select += [f"s.r{i} AS s_r{i}" for i in range(nc)] + [f"t.r{i} AS t_r{i}" for i in range(nc)]
        select += [f"COALESCE(s.k{i}, t.k{i}) AS s_k{i}" for i in range(nk)]
        for i, c in enumerate(self.plan.columns):
            select.append(f"CASE WHEN s.p IS NULL OR t.p IS NULL THEN 0 "
                          f"WHEN {self._match(f's.n{i}', f't.n{i}', c)} THEN 0 ELSE 1 END AS x{i}")
        any_bad = " + ".join(f"x{i}" for i in range(nc)) or "0"
        not_dup = lambda alias: f"NOT EXISTS (SELECT 1 FROM dk WHERE {self._keys_eq('dk', alias)})"
        return f"""WITH
src AS ({self._side_cte(self.source_rel, 'source')}),
tgt AS ({self._side_cte(self.target_rel, 'target')}),
src_d AS (SELECT {keys}, COUNT(*) AS c FROM src GROUP BY {keys} HAVING COUNT(*) > 1),
tgt_d AS (SELECT {keys}, COUNT(*) AS c FROM tgt GROUP BY {keys} HAVING COUNT(*) > 1),
dk AS (SELECT {keys} FROM src_d UNION SELECT {keys} FROM tgt_d),
src_u AS (SELECT s.* FROM src s WHERE {not_dup('s')}),
tgt_u AS (SELECT t.* FROM tgt t WHERE {not_dup('t')}),
j AS (SELECT {', '.join(select)} FROM src_u s FULL OUTER JOIN tgt_u t ON {self._keys_eq('s', 't')}),
j2 AS (SELECT j.*, CASE WHEN {any_bad} > 0 THEN 1 ELSE 0 END AS xm FROM j)
"""

    def counts_sql(self) -> str:
        nc = len(self.plan.columns)
        both = "sp IS NOT NULL AND tp IS NOT NULL"
        aggs = ["SUM(CASE WHEN tp IS NULL THEN 1 ELSE 0 END) AS mit",
                "SUM(CASE WHEN sp IS NULL THEN 1 ELSE 0 END) AS mis",
                f"SUM(CASE WHEN {both} AND xm = 1 THEN 1 ELSE 0 END) AS bad",
                f"SUM(CASE WHEN {both} AND xm = 0 THEN 1 ELSE 0 END) AS good"]
        aggs += [f"SUM(x{i}) AS cx{i}" for i in range(nc)]
        return (self.ctes() + "SELECT a.cs, b.ct, c.cd, d.* FROM "
                "(SELECT COUNT(*) AS cs FROM src) a "
                "CROSS JOIN (SELECT COUNT(*) AS ct FROM tgt) b "
                "CROSS JOIN (SELECT COUNT(*) AS cd FROM dk) c "
                f"CROSS JOIN (SELECT {', '.join(aggs)} FROM j2) d")

    def exceptions_sql(self, limit: Optional[int]) -> str:
        cols = ", ".join(self.j_columns)
        ex = (f"ex AS (SELECT 'T' AS cat, {cols} FROM j2 WHERE tp IS NULL "
              f"UNION ALL SELECT 'S' AS cat, {cols} FROM j2 WHERE sp IS NULL "
              f"UNION ALL SELECT 'M' AS cat, {cols} FROM j2 WHERE sp IS NOT NULL AND tp IS NOT NULL AND xm = 1)")
        return self._ranked(ex, "cat", ["cat"] + self.j_columns,
                            [f"s_k{i}" for i in range(len(self.plan.keys))], limit)

    def duplicates_sql(self, limit: Optional[int]) -> str:
        keys = self._key_list
        dups = (f"ex AS (SELECT 'Source' AS side, {keys}, c FROM src_d "
                f"UNION ALL SELECT 'Target' AS side, {keys}, c FROM tgt_d)")
        key_cols = [f"k{i}" for i in range(len(self.plan.keys))]
        return self._ranked(dups, "side", ["side"] + key_cols + ["c"], key_cols, limit)

    def _ranked(self, ex_cte: str, part: str, cols: List[str], order: List[str], limit: Optional[int]) -> str:
        sql = self.ctes() + ", " + ex_cte + " "
        if limit is None:
            return sql + f"SELECT {', '.join(cols)} FROM ex"
        return (sql + f", ranked AS (SELECT ex.*, ROW_NUMBER() OVER (PARTITION BY {part} ORDER BY {', '.join(order)}) AS rn FROM ex) "
                f"SELECT {', '.join(cols)} FROM ranked WHERE rn <= {int(limit)}")

    # ---- execution ----------------------------------------------------------
    def run(self, run: RunFn, sample_limit: Optional[int]) -> ComparisonResult:
        plan = self.plan
        nk, nc = len(plan.keys), len(plan.columns)
        result = ComparisonResult(warnings=list(plan.warnings))

        _, rows = run(self.counts_sql())
        counts = [int(v or 0) for v in rows[0]]
        (result.total_source, result.total_target, result.duplicate_key_count,
         result.missing_in_target_count, result.missing_in_source_count,
         result.mismatched_rows, result.matched_rows) = counts[:7]
        result.mismatches_by_column = {c.label: counts[7 + i] for i, c in enumerate(plan.columns)}

        # Exceptions: one query, capped per category.
        _, rows = run(self.exceptions_sql(sample_limit))
        ex = pd.DataFrame(rows, columns=["cat"] + self.j_columns)
        src_names = [k.source for k in plan.keys] + [c.source for c in plan.columns]
        tgt_names = [k.target for k in plan.keys] + [c.target for c in plan.columns]
        s_raw = [f"s_rk{i}" for i in range(nk)] + [f"s_r{i}" for i in range(nc)]
        t_raw = [f"t_rk{i}" for i in range(nk)] + [f"t_r{i}" for i in range(nc)]
        order = [f"s_k{i}" for i in range(nk)]

        def side_frame(cat, raw, names):
            part = ex[ex["cat"] == cat]
            part = part.sort_values(order, kind="stable") if len(part) else part
            return pd.DataFrame(part[raw].to_numpy(), columns=names)

        result.missing_in_target = side_frame("T", s_raw, src_names)
        result.missing_in_source = side_frame("S", t_raw, tgt_names)

        key_names = [k.source for k in plan.keys]
        records = []
        mism = ex[ex["cat"] == "M"]
        if len(mism):
            mism = mism.sort_values(order, kind="stable")
        for _, row in mism.iterrows():
            keys = [row[f"s_rk{i}"] for i in range(nk)]
            for i, col in enumerate(plan.columns):
                if int(row[f"x{i}"]) == 1:
                    records.append(keys + [col.label, row[f"s_r{i}"], row[f"t_r{i}"], rule_label(col), remark(col)])
        result.mismatches = pd.DataFrame(records, columns=key_names + MISMATCH_COLUMNS)

        if result.duplicate_key_count:
            _, rows = run(self.duplicates_sql(sample_limit))
            result.duplicate_keys = pd.DataFrame(rows, columns=["Side"] + key_names + ["Count"])
            result.warnings.append(
                f"{result.duplicate_key_count} primary key value(s) are duplicated; those rows are excluded "
                "from matching and listed under Duplicate Keys.")

        if sample_limit is not None:
            result.truncated = (
                result.missing_in_target_count > len(result.missing_in_target)
                or result.missing_in_source_count > len(result.missing_in_source)
                or result.mismatched_rows > len(mism)
                or len(result.duplicate_keys) >= sample_limit)
        return result


def plan_from_samples(config: ValidationConfig, source_cols: Sequence[str], source_rows: Rows,
                      target_cols: Sequence[str], target_rows: Rows) -> ComparisonPlan:
    """Build the plan from up to INFERENCE_SAMPLE sampled rows per side (same sample size as pandas)."""
    src = pd.DataFrame(source_rows, columns=list(source_cols)).head(INFERENCE_SAMPLE)
    tgt = pd.DataFrame(target_rows, columns=list(target_cols)).head(INFERENCE_SAMPLE)

    def sample(column: str, side: str):
        return (src if side == "source" else tgt)[column].dropna().tolist()

    return build_plan(config, list(source_cols), list(target_cols), sample)
