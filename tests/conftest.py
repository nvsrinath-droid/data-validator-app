import os
import sys

import pandas as pd
import pytest
from sqlalchemy import create_engine

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.comparator import DataComparator  # noqa: E402
from core.engines.duckdb_engine import DuckDBEngine  # noqa: E402
from core.engines.sql_pushdown import SQLPushdownEngine  # noqa: E402
from core.schemas import ColumnMap, ValidationConfig  # noqa: E402

ENGINES = ["pandas", "duckdb", "pushdown"]


def config(keys, *mappings, **kwargs) -> ValidationConfig:
    """config(["ID"], ("Amt", "Amount", "within 0.01"), ("Name", "Name"))"""
    maps = [ColumnMap(file1_column=m[0], file2_column=m[1], validation_rule=m[2] if len(m) > 2 else None)
            for m in mappings]
    return ValidationConfig(primary_keys=keys, column_mappings=maps, **kwargs)


class Runner:
    """Writes source/target as CSV (and into SQLite) and runs one engine on them,
    the same way the app feeds each engine."""

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path

    def __call__(self, engine: str, source: pd.DataFrame, target: pd.DataFrame, cfg: ValidationConfig,
                 sample_limit=None):
        f1, f2 = self.tmp_path / "source.csv", self.tmp_path / "target.csv"
        source.to_csv(f1, index=False)
        target.to_csv(f2, index=False)
        if engine == "pandas":
            return DataComparator(cfg).compare(pd.read_csv(f1), pd.read_csv(f2), sample_limit=sample_limit)
        if engine == "duckdb":
            return DuckDBEngine(cfg).compare(str(f1), str(f2), sample_limit=sample_limit)
        if engine == "pushdown":
            db = create_engine(f"sqlite:///{self.tmp_path / 'data.db'}")
            pd.read_csv(f1).to_sql("source_tbl", db, index=False, if_exists="replace")
            pd.read_csv(f2).to_sql("target_tbl", db, index=False, if_exists="replace")
            try:
                return SQLPushdownEngine(cfg).compare(db, "SELECT * FROM source_tbl", "SELECT * FROM target_tbl",
                                                      sample_limit=sample_limit)
            finally:
                db.dispose()
        raise ValueError(engine)


@pytest.fixture
def run(tmp_path):
    return Runner(tmp_path)


def norm_key(value) -> str:
    try:
        return format(float(value), "g")
    except (TypeError, ValueError):
        return str(value).strip()


def summary(result, key_cols):
    """Engine-independent view of a result, for asserting that engines agree."""
    def keys(frame, cols):
        return sorted(tuple(norm_key(r[c]) for c in cols) for _, r in frame.iterrows())

    return {
        "total_source": result.total_source,
        "total_target": result.total_target,
        "matched": result.matched_rows,
        "mismatched": result.mismatched_rows,
        "missing_in_target": result.missing_in_target_count,
        "missing_in_source": result.missing_in_source_count,
        "duplicates": result.duplicate_key_count,
        "by_column": result.mismatches_by_column,
        "mismatch_cells": sorted(
            (tuple(norm_key(r[c]) for c in key_cols), r["Column"]) for _, r in result.mismatches.iterrows()),
        "missing_in_target_keys": keys(result.missing_in_target, key_cols),
        "warnings": sorted(result.warnings),
    }
