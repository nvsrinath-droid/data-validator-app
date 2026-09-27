"""In-memory (pandas) comparison engine. This is the reference implementation;
the DuckDB and SQL pushdown engines must return the same ComparisonResult."""
from typing import List, Optional

import pandas as pd

from .normalize import INFERENCE_SAMPLE, Kind, normalize_series
from .plan import ColumnPlan, ComparisonPlan, build_plan
from .results import MISMATCH_COLUMNS, ComparisonResult
from .rules import FLOAT_EPSILON, RuleKind
from .schemas import ValidationConfig


def rule_label(col: ColumnPlan) -> str:
    if col.rule_text:
        return col.rule_text
    return "" if col.rule.kind == RuleKind.EXACT else col.rule.describe()


def remark(col: ColumnPlan) -> str:
    return "Exact match failed" if col.rule.kind == RuleKind.EXACT else f"Failed rule: {col.rule.describe()}"


def values_match(a: pd.Series, b: pd.Series, col: ColumnPlan) -> pd.Series:
    """Null-safe match of two normalized series: NULL == NULL, NULL != value."""
    a_null, b_null = a.isna(), b.isna()
    spec = col.rule

    if spec.kind == RuleKind.ABS_TOLERANCE:
        cond = (a - b).abs() <= spec.tolerance + FLOAT_EPSILON
    elif spec.kind == RuleKind.PCT_TOLERANCE:
        cond = (a - b).abs() <= a.abs() * spec.tolerance / 100.0 + FLOAT_EPSILON
    elif spec.kind == RuleKind.IGNORE_CASE:
        cond = a.str.lower() == b.str.lower()
    elif spec.kind == RuleKind.IGNORE_WHITESPACE:
        cond = a.str.replace(" ", "", regex=False) == b.str.replace(" ", "", regex=False)
    elif spec.kind == RuleKind.DATE_ONLY:
        cond = a.dt.normalize() == b.dt.normalize()
    else:
        cond = a == b

    cond = cond.astype("boolean").fillna(False).astype(bool)
    return (a_null & b_null) | (~a_null & ~b_null & cond)


class DataComparator:
    """Core logic engine for comparing two DataFrames."""

    def __init__(self, config: ValidationConfig):
        self.config = config

    def compare(self, df1: pd.DataFrame, df2: pd.DataFrame, sample_limit: Optional[int] = None) -> ComparisonResult:
        """df1 is the source (system of record), df2 the target being checked."""
        df1 = df1.reset_index(drop=True)
        df2 = df2.reset_index(drop=True)

        def sample(column: str, side: str):
            df = df1 if side == "source" else df2
            return df[column].head(INFERENCE_SAMPLE).dropna().tolist()

        plan = build_plan(self.config, list(df1.columns), list(df2.columns), sample)
        result = ComparisonResult(total_source=len(df1), total_target=len(df2), warnings=list(plan.warnings))

        key_cols = [f"__k{i}" for i in range(len(plan.keys))]
        src = self._prepare(df1, plan, "source")
        tgt = self._prepare(df2, plan, "target")

        # 1. Duplicate keys: report them and exclude those keys from the join,
        #    otherwise a 2x3 fan-out would show up as bogus mismatches.
        src_dups = src[src.duplicated(key_cols, keep=False)].groupby(key_cols, dropna=False).size()
        tgt_dups = tgt[tgt.duplicated(key_cols, keep=False)].groupby(key_cols, dropna=False).size()
        dup_frames = []
        for side, counts in (("Source", src_dups), ("Target", tgt_dups)):
            if len(counts):
                frame = counts.rename("Count").reset_index()
                frame.insert(0, "Side", side)
                dup_frames.append(frame)
        if dup_frames:
            dups = pd.concat(dup_frames, ignore_index=True)
            dup_keys = dups[key_cols].drop_duplicates()
            result.duplicate_key_count = len(dup_keys)
            result.duplicate_keys = self._limit(
                dups.rename(columns={k: p.source for k, p in zip(key_cols, plan.keys)}), sample_limit, result)
            result.warnings.append(
                f"{result.duplicate_key_count} primary key value(s) are duplicated; those rows are excluded "
                "from matching and listed under Duplicate Keys.")
            src = self._exclude(src, dup_keys, key_cols)
            tgt = self._exclude(tgt, dup_keys, key_cols)

        # 2. Outer join on normalized keys. Missing rows come from the join indicator,
        #    so they don't depend on the key being part of column_mappings.
        merged = src.merge(tgt, on=key_cols, how="outer", suffixes=("_s", "_t"), indicator=True)

        only_src = merged[merged["_merge"] == "left_only"]
        only_tgt = merged[merged["_merge"] == "right_only"]
        result.missing_in_target_count = len(only_src)
        result.missing_in_source_count = len(only_tgt)
        src_view = [k.source for k in plan.keys] + [c.source for c in plan.columns]
        tgt_view = [k.target for k in plan.keys] + [c.target for c in plan.columns]
        result.missing_in_target = self._limit(
            df1.loc[only_src["__row_s"].astype(int), src_view].reset_index(drop=True), sample_limit, result)
        result.missing_in_source = self._limit(
            df2.loc[only_tgt["__row_t"].astype(int), tgt_view].reset_index(drop=True), sample_limit, result)

        # 3. Value comparison for keys present on both sides.
        both = merged[merged["_merge"] == "both"].reset_index(drop=True)
        row_bad = pd.Series(False, index=both.index)
        details: List[pd.DataFrame] = []
        for i, col in enumerate(plan.columns):
            bad = ~values_match(both[f"__n{i}_s"], both[f"__n{i}_t"], col)
            row_bad |= bad
            result.mismatches_by_column[col.label] = int(bad.sum())
            if bad.any():
                hit = both[bad]
                src_rows = hit["__row_s"].astype(int)
                frame = df1.loc[src_rows, [k.source for k in plan.keys]].reset_index(drop=True)
                frame["Column"] = col.label
                frame["Source Value"] = df1.loc[src_rows, col.source].to_numpy()
                frame["Target Value"] = df2.loc[hit["__row_t"].astype(int), col.target].to_numpy()
                frame["Rule"] = rule_label(col)
                frame["Remarks"] = remark(col)
                frame["__order"] = src_rows.to_numpy() * len(plan.columns) + i
                details.append(frame)

        result.mismatched_rows = int(row_bad.sum())
        result.matched_rows = len(both) - result.mismatched_rows
        if details:
            mism = pd.concat(details, ignore_index=True).sort_values("__order").drop(columns="__order")
            if sample_limit is not None:
                # cap by mismatched *rows*, matching the SQL engines
                keep_rows = mism[[k.source for k in plan.keys]].drop_duplicates().head(sample_limit)
                if len(keep_rows) < result.mismatched_rows:
                    result.truncated = True
                mism = mism.merge(keep_rows, how="inner")
            result.mismatches = mism.reset_index(drop=True)
        else:
            result.mismatches = pd.DataFrame(columns=[k.source for k in plan.keys] + MISMATCH_COLUMNS)
        return result

    @staticmethod
    def _prepare(df: pd.DataFrame, plan: ComparisonPlan, side: str) -> pd.DataFrame:
        def norm(column: str, kind: Kind) -> pd.Series:
            return normalize_series(df[column], kind, plan.trim, plan.blank_as_null)

        out = pd.DataFrame(index=df.index)
        for i, k in enumerate(plan.keys):
            out[f"__k{i}"] = norm(k.source if side == "source" else k.target, k.kind)
        for i, c in enumerate(plan.columns):
            out[f"__n{i}"] = norm(c.source if side == "source" else c.target, c.kind)
        out["__row"] = df.index
        return out

    @staticmethod
    def _exclude(frame: pd.DataFrame, keys: pd.DataFrame, key_cols: List[str]) -> pd.DataFrame:
        flagged = frame.merge(keys, on=key_cols, how="left", indicator="__dup")
        return flagged[flagged["__dup"] == "left_only"].drop(columns="__dup")

    @staticmethod
    def _limit(frame: pd.DataFrame, limit: Optional[int], result: ComparisonResult) -> pd.DataFrame:
        if limit is not None and len(frame) > limit:
            result.truncated = True
            return frame.head(limit).reset_index(drop=True)
        return frame
