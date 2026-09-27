import pytest
from pydantic import ValidationError

from core.normalize import Kind, infer_kind
from core.rules import EXACT, RuleKind, RuleSpec, parse_rule


@pytest.mark.parametrize("text, kind, tol", [
    ("within 0.01", RuleKind.ABS_TOLERANCE, 0.01),
    ("Must be within $5", RuleKind.ABS_TOLERANCE, 5.0),
    ("tolerance of 2.50", RuleKind.ABS_TOLERANCE, 2.5),
    ("+/- .5", RuleKind.ABS_TOLERANCE, 0.5),
    ("within 1,000", RuleKind.ABS_TOLERANCE, 1000.0),
    ("+/- 5%", RuleKind.PCT_TOLERANCE, 5.0),
    ("within 0.5 percent", RuleKind.PCT_TOLERANCE, 0.5),
    ("± 2.5 %", RuleKind.PCT_TOLERANCE, 2.5),
    ("Ignore case", RuleKind.IGNORE_CASE, None),
    ("case-insensitive", RuleKind.IGNORE_CASE, None),
    ("ignore spaces", RuleKind.IGNORE_WHITESPACE, None),
    ("same date, ignore time", RuleKind.DATE_ONLY, None),
    ("exact match", RuleKind.EXACT, None),
])
def test_parse_rule(text, kind, tol):
    spec, warning = parse_rule(text)
    assert warning is None
    assert spec.kind == kind
    assert spec.tolerance == tol


@pytest.mark.parametrize("text", [None, "", "  ", "None", "nan"])
def test_empty_rule_is_exact_without_warning(text):
    assert parse_rule(text) == (EXACT, None)


@pytest.mark.parametrize("text", ["within tolerance", "approximately equal", "sum of lines"])
def test_unrecognised_rule_warns(text):
    spec, warning = parse_rule(text)
    assert spec == EXACT
    assert warning and text in warning


def test_rule_spec_is_validated():
    with pytest.raises(ValidationError):
        RuleSpec(kind="abs_tolerance")               # missing tolerance
    with pytest.raises(ValidationError):
        RuleSpec(kind="abs_tolerance", tolerance=-1)
    with pytest.raises(ValidationError):
        RuleSpec(kind="python", tolerance=None)      # unknown kind
    with pytest.raises(ValidationError):
        RuleSpec(kind="exact", code="import os")     # extra fields rejected


@pytest.mark.parametrize("a, b, kind", [
    ([100, 200], ["100.00", " 200 "], Kind.NUMERIC),
    (["2024-01-15"], ["2024-01-15 10:00:00"], Kind.DATE),
    (["00123", "ABC"], ["123"], Kind.STRING),
    ([None, float("nan")], [""], Kind.STRING),
    ([True], [False], Kind.STRING),
])
def test_infer_kind(a, b, kind):
    assert infer_kind(a, b) == kind
