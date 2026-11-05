"""Data quality checks as data, never code.

A check is a validated pydantic spec (unknown fields and unknown check types are rejected),
so an LLM may *suggest* checks but can only ever return values from this closed set.
Specs name columns and, for referential integrity, a reference table by *name*; file paths
are supplied by the caller and never by a spec.
"""
import math
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Annotated, List, Literal, Optional, Union

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.normalize import Kind

Severity = Literal["fail", "warn"]
# "inconclusive": the check could not give a meaningful answer for this data (not a failure; see Outliers).
Status = Literal["pass", "warn", "fail", "error", "inconclusive"]

_AGE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(m|min|h|d)\s*$", re.IGNORECASE)
_AGE_SECONDS = {"m": 60, "min": 60, "h": 3600, "d": 86400}
MAX_AGE = timedelta(days=36500)  # 100 years; anything larger is a mistake, and timedelta overflows eventually


def parse_age(text: str) -> timedelta:
    """'90m', '36h', '2d' -> timedelta (at most 100 years)."""
    m = _AGE_RE.match(text or "")
    if not m:
        raise ValueError(f"Invalid age {text!r}; use a number and a unit m, h or d (for example '36h')")
    seconds = float(m.group(1)) * _AGE_SECONDS[m.group(2).lower()]
    if not math.isfinite(seconds) or seconds > MAX_AGE.total_seconds():
        raise ValueError(f"Age {text!r} is too large (the maximum is 100 years)")
    return timedelta(seconds=seconds)


class _Check(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str
    severity: Severity = "fail"


class NullRate(_Check):
    """Share of NULL or blank values must not exceed max_pct (0-100)."""
    type: Literal["null_rate"] = "null_rate"
    max_pct: float = Field(default=0.0, ge=0, le=100, allow_inf_nan=False)

    @property
    def label(self) -> str:
        return f"null rate of {self.column} <= {self.max_pct:g}%"


class Distinct(_Check):
    """Distinct non-null values: unique=True means no value repeats; bounds are optional."""
    type: Literal["distinct"] = "distinct"
    unique: bool = False
    min_distinct: Optional[int] = Field(default=None, ge=0)
    max_distinct: Optional[int] = Field(default=None, ge=0)

    @property
    def label(self) -> str:
        parts = ["unique"] if self.unique else []
        if self.min_distinct is not None:
            parts.append(f">= {self.min_distinct} distinct")
        if self.max_distinct is not None:
            parts.append(f"<= {self.max_distinct} distinct")
        return f"{self.column}: " + (", ".join(parts) or "distinct count")


class TypeDrift(_Check):
    """Non-blank values that do not parse as the expected kind must not exceed max_pct.

    expected=None takes the kind from the saved baseline profile. A STRING column
    has nothing to violate, so it always conforms.
    """
    type: Literal["type_drift"] = "type_drift"
    expected: Optional[Kind] = None
    max_pct: float = Field(default=0.0, ge=0, le=100, allow_inf_nan=False)

    @property
    def label(self) -> str:
        return f"{self.column} values conform to {self.expected.value if self.expected else 'baseline type'}"


class Freshness(_Check):
    """as_of minus the newest value in a date column must not exceed max_age."""
    type: Literal["freshness"] = "freshness"
    max_age: str = "24h"

    @field_validator("max_age")
    @classmethod
    def _valid_age(cls, v: str) -> str:
        parse_age(v)
        return v

    @property
    def max_age_delta(self):
        return parse_age(self.max_age)

    @property
    def label(self) -> str:
        return f"{self.column} no older than {self.max_age}"


class RefIntegrity(_Check):
    """Every non-null value must exist in ref_column of the named reference table (orphans <= max_orphans)."""
    type: Literal["ref_integrity"] = "ref_integrity"
    ref_name: str
    ref_column: str
    max_orphans: int = Field(default=0, ge=0)

    @property
    def label(self) -> str:
        return f"{self.column} exists in {self.ref_name}.{self.ref_column}"


class Outliers(_Check):
    """Numeric values outside the IQR fences (k x IQR) or beyond k standard deviations."""
    type: Literal["outliers"] = "outliers"
    method: Literal["iqr", "zscore"] = "iqr"
    k: Optional[float] = Field(default=None, gt=0, allow_inf_nan=False)
    max_count: int = Field(default=0, ge=0)

    @property
    def threshold(self) -> float:
        return self.k if self.k is not None else (1.5 if self.method == "iqr" else 3.0)

    @property
    def label(self) -> str:
        return f"{self.column} outliers ({self.method}, k={self.threshold:g})"


CheckSpec = Annotated[Union[NullRate, Distinct, TypeDrift, Freshness, RefIntegrity, Outliers],
                      Field(discriminator="type")]


class QualityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checks: List[CheckSpec]


@dataclass
class CheckResult:
    check: Union[NullRate, Distinct, TypeDrift, Freshness, RefIntegrity, Outliers]
    status: Status
    metric: Optional[float] = None       # the measured value (percent, count, age in hours, ...)
    violations: int = 0                  # rows/values that broke the check
    message: str = ""
    sample: pd.DataFrame = field(default_factory=pd.DataFrame)  # capped; stays local, never sent to an LLM


@dataclass
class QualityResult:
    row_count: int = 0
    results: List[CheckResult] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        return any(r.status in ("fail", "error") for r in self.results)
