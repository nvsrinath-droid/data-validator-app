"""Engine-independent comparison plan.

Resolves a ValidationConfig against the actual source/target columns into
key pairs and compared-column pairs, each with a Kind and a RuleSpec. Every
engine builds its plan with build_plan(), so all engines agree on which
columns are compared, how, and which warnings the user sees.
"""
from dataclasses import dataclass, field
from typing import Callable, List, Sequence

from .normalize import Kind, infer_kind
from .rules import EXACT, RuleKind, RuleSpec, parse_rule
from .schemas import ValidationConfig

_RULE_KIND = {
    RuleKind.ABS_TOLERANCE: Kind.NUMERIC,
    RuleKind.PCT_TOLERANCE: Kind.NUMERIC,
    RuleKind.DATE_ONLY: Kind.DATE,
    RuleKind.IGNORE_CASE: Kind.STRING,
    RuleKind.IGNORE_WHITESPACE: Kind.STRING,
}


@dataclass
class ColumnPlan:
    source: str
    target: str
    kind: Kind
    rule: RuleSpec = EXACT
    rule_text: str = ""

    @property
    def label(self) -> str:
        return self.source if self.source == self.target else f"{self.source} -> {self.target}"


@dataclass
class ComparisonPlan:
    keys: List[ColumnPlan]
    columns: List[ColumnPlan]
    trim: bool = True
    blank_as_null: bool = True
    warnings: List[str] = field(default_factory=list)


# (column_name, side) -> sample of that column's values; side is "source" or "target"
SampleFn = Callable[[str, str], Sequence]


def build_plan(config: ValidationConfig, source_columns: Sequence[str], target_columns: Sequence[str],
               sample: SampleFn) -> ComparisonPlan:
    if not config.primary_keys:
        raise ValueError("At least one primary key is required to match rows between source and target.")

    ignore = set(config.ignore_columns or [])
    target_of = {m.file1_column: m.file2_column for m in config.column_mappings}
    warnings: List[str] = []

    def check(col: str, cols: Sequence[str], side: str):
        if col not in cols:
            raise ValueError(f"Column '{col}' was not found in the {side} data. Available columns: {list(cols)}")

    def kind_for(src: str, tgt: str, forced: str = "auto") -> Kind:
        if forced != "auto":
            return Kind(forced)
        return infer_kind(sample(src, "source"), sample(tgt, "target"))

    keys = []
    for pk in config.primary_keys:
        tgt = target_of.get(pk, pk)
        check(pk, source_columns, "source")
        check(tgt, target_columns, "target")
        keys.append(ColumnPlan(pk, tgt, kind_for(pk, tgt)))

    columns = []
    for m in config.column_mappings:
        if m.file1_column in config.primary_keys or m.file1_column in ignore:
            continue
        check(m.file1_column, source_columns, "source")
        check(m.file2_column, target_columns, "target")

        if m.rule_spec is not None:
            spec = m.rule_spec
        else:
            spec, warning = parse_rule(m.validation_rule)
            if warning:
                warnings.append(f"{m.file1_column}: {warning}")

        kind = kind_for(m.file1_column, m.file2_column, m.compare_as)
        required = _RULE_KIND.get(spec.kind)
        if required and required != kind:
            if m.compare_as == "auto":
                warnings.append(
                    f"{m.file1_column}: rule '{spec.describe()}' needs {required.value} values but the data "
                    f"looks like {kind.value}; comparing as {required.value} (unparseable values become NULL).")
            kind = required

        rule_text = (m.validation_rule or "").strip()
        if rule_text.lower() in ("none", "nan"):
            rule_text = ""
        columns.append(ColumnPlan(m.file1_column, m.file2_column, kind, spec, rule_text))

    return ComparisonPlan(keys, columns, config.trim_strings, config.blank_as_null, warnings)
