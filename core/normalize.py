"""Type-aware value normalization shared by all engines.

Each compared column pair gets a Kind:
  NUMERIC - compared as numbers, so 100 == 100.00 == " 100 "
  DATE    - ISO-8601 dates/timestamps compared as timestamps, so 2024-01-15 == 2024-01-15 00:00:00
  STRING  - compared as trimmed text (JDE pads CHAR fields); blanks become NULL by default

The pandas engine uses normalize_series(); the SQL engines render the same
semantics per dialect in core/engines/sql_builder.py.
"""
import datetime as dt
import decimal
import re
from enum import Enum
from typing import Iterable

import numpy as np
import pandas as pd

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?$")
NUMERIC_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")

# How many non-null values per side are inspected to infer a column's kind.
INFERENCE_SAMPLE = 1000


class Kind(str, Enum):
    NUMERIC = "numeric"
    DATE = "date"
    STRING = "string"


def _classify(value) -> Kind:
    if isinstance(value, (bool, np.bool_)):
        return Kind.STRING
    if isinstance(value, (int, float, decimal.Decimal, np.integer, np.floating)):
        return Kind.NUMERIC
    if isinstance(value, (dt.date, dt.datetime, pd.Timestamp, np.datetime64)):
        return Kind.DATE
    text = str(value).strip()
    if NUMERIC_RE.match(text):
        return Kind.NUMERIC
    if ISO_DATE_RE.match(text):
        return Kind.DATE
    return Kind.STRING


def _non_blank(values: Iterable) -> list:
    out = []
    for v in values:
        if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NaT:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        out.append(v)
    return out


def infer_kind(source_values: Iterable, target_values: Iterable) -> Kind:
    """Pick one comparison kind for a column pair from sample values of both sides.

    NUMERIC/DATE only when every non-blank value on both sides qualifies;
    otherwise fall back to STRING so nothing is silently coerced to NULL.
    """
    values = _non_blank(source_values) + _non_blank(target_values)
    if not values:
        return Kind.STRING
    kinds = {_classify(v) for v in values}
    return kinds.pop() if len(kinds) == 1 else Kind.STRING


def normalize_series(s: pd.Series, kind: Kind, trim: bool = True, blank_as_null: bool = True) -> pd.Series:
    """Pandas implementation of the per-kind normalization."""
    if kind == Kind.NUMERIC:
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            return s.astype("float64")
        return pd.to_numeric(s.astype("string").str.strip(), errors="coerce").astype("float64")

    if kind == Kind.DATE:
        if pd.api.types.is_datetime64_any_dtype(s):
            return s.dt.tz_localize(None) if getattr(s.dt, "tz", None) is not None else s
        return pd.to_datetime(s.astype("string").str.strip(), errors="coerce", format="ISO8601")

    out = s.astype("string")
    if trim:
        out = out.str.strip()
    if blank_as_null:
        out = out.mask(out == "")
    return out
