"""Runs quality checks against one table in DuckDB.

Only counts, a handful of statistics and a capped sample of offending values come back;
the sample is for the local user and is never put into an LLM prompt (see ai/quality_summary.py).
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Optional, Union

import duckdb
import pandas as pd

from core.engines.duckdb_engine import load_table
from core.engines.sql_builder import normalize_expr
from core.normalize import Kind, infer_kind

from .baseline import compare_profiles
from .profile import DIALECT, TableProfile, column_sample, profile_table, quote
from .specs import (CheckResult, CheckSpec, Distinct, Freshness, NullRate, Outliers, QualityConfig,
                    QualityResult, RefIntegrity, Severity, TypeDrift)

EPS = 1e-9
DEFAULT_SAMPLE_LIMIT = 20


def _status(ok: bool, severity: Severity) -> str:
    return "pass" if ok else severity


def _num(x) -> float:
    return float(repr(float(x)))  # plain Python float, whatever DuckDB/numpy handed back


@dataclass
class _Context:
    conn: duckdb.DuckDBPyConnection
    profile: TableProfile
    references: Dict[str, str]
    baseline: Optional[TableProfile]
    as_of: datetime
    limit: int
    _loaded: Dict[str, str] = field(default_factory=dict)

    def frame(self, sql: str) -> pd.DataFrame:
        return self.conn.execute(sql).df()

    def one(self, sql: str):
        return self.conn.execute(sql).fetchone()

    def ref_table(self, name: str) -> str:
        if name not in self.references:
            raise ValueError(f"Unknown reference table {name!r}. Provided: {sorted(self.references) or 'none'}")
        if name not in self._loaded:
            table = f"ref_{len(self._loaded)}"
            load_table(self.conn, self.references[name], table, raw=True)
            self._loaded[name] = table
        return self._loaded[name]

    def columns_of(self, table: str) -> List[str]:
        return [r[0] for r in self.conn.execute(f"DESCRIBE {table}").fetchall()]


# ---- individual checks -----------------------------------------------------------------

def _null_rate(ctx: _Context, c: NullRate) -> CheckResult:
    col = ctx.profile.column(c.column)
    ok = col.null_pct <= c.max_pct + EPS
    q = quote(c.column)
    sample = ctx.frame(
        f"SELECT rowid + 1 AS _row, {q} AS value FROM t WHERE ({normalize_expr(DIALECT, q, Kind.STRING)}) IS NULL "
        f"LIMIT {ctx.limit}") if not ok else pd.DataFrame()
    return CheckResult(c, _status(ok, c.severity), col.null_pct, col.null_count,
                       f"{col.null_count:,} of {ctx.profile.row_count:,} values are NULL or blank "
                       f"({col.null_pct:.2f}%; limit {c.max_pct:g}%).", sample)


def _distinct(ctx: _Context, c: Distinct) -> CheckResult:
    col = ctx.profile.column(c.column)
    problems, violations = [], 0
    duplicates = col.non_null_count - col.distinct_count
    if c.unique and duplicates:
        problems.append(f"{duplicates:,} non-null rows repeat an earlier value")
        violations += duplicates
    if c.min_distinct is not None and col.distinct_count < c.min_distinct:
        problems.append(f"{col.distinct_count:,} distinct values, expected at least {c.min_distinct:,}")
        violations += 1
    if c.max_distinct is not None and col.distinct_count > c.max_distinct:
        problems.append(f"{col.distinct_count:,} distinct values, expected at most {c.max_distinct:,}")
        violations += 1
    sample = pd.DataFrame()
    if c.unique and duplicates:
        value = normalize_expr(DIALECT, quote(c.column), col.kind)
        sample = ctx.frame(f"SELECT CAST({value} AS VARCHAR) AS value, COUNT(*) AS rows FROM t "
                           f"WHERE ({value}) IS NOT NULL GROUP BY 1 HAVING COUNT(*) > 1 "
                           f"ORDER BY rows DESC, value LIMIT {ctx.limit}")
    message = "; ".join(problems) or f"{col.distinct_count:,} distinct values across {col.non_null_count:,} non-null rows."
    return CheckResult(c, _status(not problems, c.severity), float(col.distinct_count), violations, message, sample)


def _type_drift(ctx: _Context, c: TypeDrift) -> CheckResult:
    col = ctx.profile.column(c.column)
    expected = c.expected
    if expected is None:
        if ctx.baseline is None:
            raise ValueError("type_drift needs 'expected' or a baseline profile to take the type from")
        expected = ctx.baseline.column(c.column).kind
    bad, sample = 0, pd.DataFrame()
    if expected != Kind.STRING:
        q = quote(c.column)
        guard = (f"({normalize_expr(DIALECT, q, Kind.STRING)}) IS NOT NULL "
                 f"AND ({normalize_expr(DIALECT, q, expected)}) IS NULL")
        bad = ctx.one(f"SELECT COUNT(*) FROM t WHERE {guard}")[0]
        if bad:
            sample = ctx.frame(f"SELECT rowid + 1 AS _row, {q} AS value FROM t WHERE {guard} LIMIT {ctx.limit}")
    pct = 100.0 * bad / col.non_null_count if col.non_null_count else 0.0
    ok = pct <= c.max_pct + EPS
    return CheckResult(c, _status(ok, c.severity), pct, bad,
                       f"{bad:,} of {col.non_null_count:,} non-blank values are not {expected.value} "
                       f"({pct:.2f}%; limit {c.max_pct:g}%).", sample)


def _freshness(ctx: _Context, c: Freshness) -> CheckResult:
    ctx.profile.column(c.column)  # existence
    newest = ctx.one(f"SELECT MAX({normalize_expr(DIALECT, quote(c.column), Kind.DATE)}) FROM t")[0]
    if newest is None:
        return CheckResult(c, c.severity, None, 1, f"{c.column} has no parseable dates.")
    age = ctx.as_of - newest
    hours = age.total_seconds() / 3600
    ok = age <= c.max_age_delta
    note = " The newest value is in the future." if hours < 0 else ""
    return CheckResult(c, _status(ok, c.severity), hours, 0 if ok else 1,
                       f"Newest {c.column} is {newest:%Y-%m-%d %H:%M:%S}, {hours:.1f}h before "
                       f"{ctx.as_of:%Y-%m-%d %H:%M:%S} (limit {c.max_age}).{note}")


def _ref_integrity(ctx: _Context, c: RefIntegrity) -> CheckResult:
    child_col = ctx.profile.column(c.column)
    ref = ctx.ref_table(c.ref_name)
    if c.ref_column not in ctx.columns_of(ref):
        raise ValueError(f"Column {c.ref_column!r} not found in reference {c.ref_name!r}. "
                         f"Available: {ctx.columns_of(ref)}")
    kind = infer_kind(column_sample(ctx.conn, "t", c.column), column_sample(ctx.conn, ref, c.ref_column))
    child = normalize_expr(DIALECT, quote(c.column), kind)
    parent = normalize_expr(DIALECT, quote(c.ref_column), kind)
    orphan = f"({child}) IS NOT NULL AND ({child}) NOT IN (SELECT {parent} FROM {ref} WHERE ({parent}) IS NOT NULL)"
    rows, distinct = ctx.one(f"SELECT COUNT(*), COUNT(DISTINCT {child}) FROM t WHERE {orphan}")
    ok = rows <= c.max_orphans
    sample = ctx.frame(f"SELECT CAST({child} AS VARCHAR) AS value, COUNT(*) AS rows FROM t WHERE {orphan} "
                       f"GROUP BY 1 ORDER BY rows DESC, value LIMIT {ctx.limit}") if rows else pd.DataFrame()
    return CheckResult(c, _status(ok, c.severity), float(rows), rows,
                       f"{rows:,} of {child_col.non_null_count:,} non-null {c.column} rows ({distinct:,} distinct values) "
                       f"have no match in {c.ref_name}.{c.ref_column} (limit {c.max_orphans:,}).", sample)


def _outliers(ctx: _Context, c: Outliers) -> CheckResult:
    col = ctx.profile.column(c.column)
    if col.kind != Kind.NUMERIC:
        raise ValueError(f"outliers needs a numeric column; {c.column!r} is {col.kind.value}")
    q = quote(c.column)
    v = normalize_expr(DIALECT, q, Kind.NUMERIC)
    if c.method == "iqr":
        q1, q3 = ctx.one(f"SELECT quantile_cont({v}, 0.25), quantile_cont({v}, 0.75) FROM t")
        if q1 is None:
            return CheckResult(c, "pass", 0.0, 0, "No numeric values to check.")
        iqr = _num(q3) - _num(q1)
        lo, hi = _num(q1) - c.threshold * iqr, _num(q3) + c.threshold * iqr
        how = f"outside [{lo:g}, {hi:g}]"
    else:
        mean, sd = ctx.one(f"SELECT AVG({v}), STDDEV_SAMP({v}) FROM t")
        if mean is None or not sd:
            return CheckResult(c, "pass", 0.0, 0, "No spread in the values, so nothing can be an outlier.")
        lo, hi = _num(mean) - c.threshold * _num(sd), _num(mean) + c.threshold * _num(sd)
        how = f"more than {c.threshold:g} standard deviations from the mean ({_num(mean):g})"
    cond = f"({v}) < {lo!r} OR ({v}) > {hi!r}"
    count = ctx.one(f"SELECT COUNT(*) FROM t WHERE {cond}")[0]
    ok = count <= c.max_count
    sample = ctx.frame(f"SELECT rowid + 1 AS _row, {q} AS value FROM t WHERE {cond} "
                       f"ORDER BY GREATEST({lo!r} - ({v}), ({v}) - {hi!r}) DESC LIMIT {ctx.limit}") if count else pd.DataFrame()
    return CheckResult(c, _status(ok, c.severity), float(count), count,
                       f"{count:,} values {how} (limit {c.max_count:,}).", sample)


_RUNNERS: Dict[str, Callable[[_Context, CheckSpec], CheckResult]] = {
    "null_rate": _null_rate, "distinct": _distinct, "type_drift": _type_drift,
    "freshness": _freshness, "ref_integrity": _ref_integrity, "outliers": _outliers,
}


class QualityEngine:
    """
    checks      - CheckSpec objects (or a QualityConfig)
    references  - name -> file path, for ref_integrity checks. Paths come from the caller, never from a spec.
    baseline    - a saved TableProfile: supplies the type for type_drift checks without `expected`,
                  and column-level drift is reported in result.warnings
    as_of       - "now" for freshness checks (naive datetime); pass a fixed value to make runs reproducible
    """

    def __init__(self, checks: Union[QualityConfig, Iterable[CheckSpec]], references: Optional[Dict[str, str]] = None,
                 baseline: Optional[TableProfile] = None, as_of: Optional[datetime] = None,
                 sample_limit: int = DEFAULT_SAMPLE_LIMIT):
        self.checks = list(checks.checks if isinstance(checks, QualityConfig) else checks)
        self.references = dict(references or {})
        self.baseline = baseline
        if as_of is not None and as_of.tzinfo is not None:
            raise ValueError("as_of must be a naive datetime (values are compared without time zones)")
        self.as_of = as_of or datetime.now()
        self.sample_limit = sample_limit

    def run(self, path: str) -> QualityResult:
        conn = duckdb.connect(database=":memory:")
        try:
            load_table(conn, path, "t", raw=True)
            profile = profile_table(conn, "t")
            ctx = _Context(conn, profile, self.references, self.baseline, self.as_of, self.sample_limit)
            result = QualityResult(row_count=profile.row_count)
            if self.baseline is not None:
                result.warnings += compare_profiles(self.baseline, profile)
            for check in self.checks:
                try:
                    result.results.append(_RUNNERS[check.type](ctx, check))
                except (ValueError, duckdb.Error) as e:
                    result.results.append(CheckResult(check, "error", message=str(e)))
            return result
        finally:
            conn.close()
