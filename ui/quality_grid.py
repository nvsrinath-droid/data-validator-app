"""Checks grid <-> check specs. Pure functions (no Streamlit) so they can be tested directly.

One grid row is one check. Columns that do not apply to a row's type stay blank. Rows are validated into the
same closed-set specs the engine and the LLM path use, so the grid can express nothing the engine cannot run.
"""
import math
from typing import List, Tuple

import pandas as pd
from pydantic import TypeAdapter, ValidationError

from core.quality.specs import CheckSpec

CHECK_TYPES = ["null_rate", "distinct", "type_drift", "freshness", "outliers", "ref_integrity"]
GRID_COLUMNS = ["type", "column", "severity", "max_pct", "unique", "min_distinct", "max_distinct",
                "expected", "max_age", "method", "k", "max_count"]
# Which parameter columns each type reads (everything else in the row is ignored for that type)
NUMBER_COLUMNS = ["max_pct", "min_distinct", "max_distinct", "k", "max_count"]
PARAMS = {
    "null_rate": ["max_pct"],
    "distinct": ["unique", "min_distinct", "max_distinct"],
    "type_drift": ["expected", "max_pct"],
    "freshness": ["max_age"],
    "outliers": ["method", "k", "max_count"],
}
REF_MESSAGE = ("ref_integrity needs a reference file, which the web UI does not support yet. "
               "Run it from the command line with --ref NAME=PATH (see README).")
_ADAPTER = TypeAdapter(CheckSpec)


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA or (isinstance(v, str) and not v.strip())


def specs_to_frame(checks) -> pd.DataFrame:
    rows = []
    for c in checks:
        data = c.model_dump(mode="json", exclude_none=True)
        rows.append({col: data.get(col) for col in GRID_COLUMNS})
    frame = pd.DataFrame(rows, columns=GRID_COLUMNS)
    for col in NUMBER_COLUMNS:
        frame[col] = pd.to_numeric(frame[col], errors="coerce").astype("float64")
    frame["unique"] = frame["unique"].astype("boolean")
    return frame


def empty_frame() -> pd.DataFrame:
    return specs_to_frame([])


def frame_to_specs(frame: pd.DataFrame, columns: List[str]) -> Tuple[list, List[str]]:
    """Grid -> (valid specs, one error message per bad row). A bad row never stops the others from being read."""
    specs, errors = [], []
    for i, row in enumerate(frame.to_dict("records"), start=1):
        if all(_blank(row.get(c)) or row.get(c) is False for c in GRID_COLUMNS):
            continue                                   # an untouched blank row
        kind = row.get("type")
        if _blank(kind):
            errors.append(f"Row {i}: choose a check type.")
            continue
        if kind == "ref_integrity":
            errors.append(f"Row {i}: {REF_MESSAGE}")
            continue
        if kind not in PARAMS:
            errors.append(f"Row {i}: unknown check type {kind!r}.")
            continue
        column = row.get("column")
        if _blank(column) or column not in columns:
            errors.append(f"Row {i}: {kind} needs a column from the table (got {column!r}).")
            continue
        data = {"type": kind, "column": column}
        if not _blank(row.get("severity")):
            data["severity"] = row["severity"]
        for p in PARAMS[kind]:
            if not _blank(row.get(p)):
                v = row[p]
                data[p] = bool(v) if p == "unique" else v
        for p in ("min_distinct", "max_distinct", "max_count"):    # the grid stores numbers as floats
            if isinstance(data.get(p), float):
                data[p] = int(data[p]) if float(data[p]).is_integer() else data[p]
        try:
            specs.append(_ADAPTER.validate_python(data))
        except ValidationError as e:
            err = e.errors()[0]
            where = ".".join(str(x) for x in err["loc"] if x != kind)
            errors.append(f"Row {i}: {where + ': ' if where else ''}{err['msg']}")
    return specs, errors
