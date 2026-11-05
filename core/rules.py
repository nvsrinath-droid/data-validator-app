"""Plain-English validation rules -> a small, validated rule spec.

Rules are never executed as code. Every engine renders a RuleSpec itself
(pandas expressions, or SQL for DuckDB / pushdown), so a rule means the same
thing everywhere.
"""
import re
from enum import Enum
from typing import Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Added to every tolerance so that e.g. 100.00 vs 100.01 "within 0.01" passes
# despite binary floating point (|diff| == 0.010000000000005).
FLOAT_EPSILON = 1e-9


class RuleKind(str, Enum):
    EXACT = "exact"
    ABS_TOLERANCE = "abs_tolerance"      # |a - b| <= tolerance
    PCT_TOLERANCE = "pct_tolerance"      # |a - b| <= |a| * tolerance / 100  (a = source value)
    IGNORE_CASE = "ignore_case"
    IGNORE_WHITESPACE = "ignore_whitespace"
    DATE_ONLY = "date_only"              # compare the date part, ignore time of day


class RuleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: RuleKind
    tolerance: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check_tolerance(self):
        needs_tol = self.kind in (RuleKind.ABS_TOLERANCE, RuleKind.PCT_TOLERANCE)
        if needs_tol and self.tolerance is None:
            raise ValueError(f"{self.kind.value} requires a tolerance")
        if not needs_tol and self.tolerance is not None:
            raise ValueError(f"{self.kind.value} does not take a tolerance")
        return self

    @property
    def is_numeric(self) -> bool:
        return self.kind in (RuleKind.ABS_TOLERANCE, RuleKind.PCT_TOLERANCE)

    def describe(self) -> str:
        if self.kind == RuleKind.ABS_TOLERANCE:
            return f"within ±{self.tolerance:g}"
        if self.kind == RuleKind.PCT_TOLERANCE:
            return f"within ±{self.tolerance:g}% of source"
        return {
            RuleKind.EXACT: "exact match",
            RuleKind.IGNORE_CASE: "case-insensitive match",
            RuleKind.IGNORE_WHITESPACE: "match ignoring whitespace",
            RuleKind.DATE_ONLY: "same date (time ignored)",
        }[self.kind]


EXACT = RuleSpec(kind=RuleKind.EXACT)

_NUMBER = r"(\d+(?:\.\d*)?|\.\d+)"
_TOLERANCE_WORDS = ("tolerance", "within", "+/-", "±", "plus or minus", "off by", "variance", "difference")
_PCT_RE = re.compile(_NUMBER + r"\s*(%|percent|pct)")


def parse_rule(text: Optional[str]) -> Tuple[RuleSpec, Optional[str]]:
    """Parse a plain-English rule.

    Returns (spec, warning). Unrecognised rules fall back to an exact match and
    return a warning so the UI can tell the user instead of failing silently.
    """
    if text is None or not str(text).strip() or str(text).strip().lower() in ("none", "nan"):
        return EXACT, None

    raw = str(text).strip()
    rule = raw.lower().replace(",", "")

    if any(w in rule for w in _TOLERANCE_WORDS):
        pct = _PCT_RE.search(rule)
        if pct:
            return RuleSpec(kind=RuleKind.PCT_TOLERANCE, tolerance=float(pct.group(1))), None
        num = re.search(r"[$€£]?\s*" + _NUMBER, rule)
        if num:
            return RuleSpec(kind=RuleKind.ABS_TOLERANCE, tolerance=float(num.group(1))), None
        return EXACT, f"Rule '{raw}' mentions a tolerance but no number was found; using exact match."

    if "ignore case" in rule or "case insensitive" in rule or "case-insensitive" in rule:
        return RuleSpec(kind=RuleKind.IGNORE_CASE), None

    if re.search(r"ignore (white\s*space|spaces|blanks)", rule):
        return RuleSpec(kind=RuleKind.IGNORE_WHITESPACE), None

    if re.search(r"(ignore|without|exclude) time|same (day|date)|date only", rule):
        return RuleSpec(kind=RuleKind.DATE_ONLY), None

    if re.fullmatch(r"(must )?(be )?(an )?(exact( match)?|match(es)? exactly|equal|equals|same)", rule):
        return EXACT, None

    return EXACT, f"Rule '{raw}' was not understood; using exact match."


def _amount(value: float) -> str:
    return f"{value:,.2f}" if round(value, 2) == value else f"{value:,g}"


def rule_preview(text: Optional[str]) -> str:
    """How a rule typed in the mapping grid will be applied, e.g. "absolute ±1.00" or "±1% of source"."""
    spec, warning = parse_rule(text)
    if warning:
        return "⚠ not understood: exact match, unless the AI can interpret it"
    if spec.kind == RuleKind.ABS_TOLERANCE:
        return f"absolute ±{_amount(spec.tolerance)}"
    if spec.kind == RuleKind.PCT_TOLERANCE:
        return f"±{spec.tolerance:g}% of source"
    return {
        RuleKind.EXACT: "exact",
        RuleKind.IGNORE_CASE: "exact, ignoring case",
        RuleKind.IGNORE_WHITESPACE: "exact, ignoring spaces",
        RuleKind.DATE_ONLY: "same date, time ignored",
    }[spec.kind]
