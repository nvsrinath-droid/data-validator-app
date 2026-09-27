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


# ---- Rule preview in the mapping grid ---------------------------------------------------------

@pytest.mark.parametrize("text, preview", [
    ("within 1", "absolute ±1.00"),           # the easy mistake: no % means an absolute amount
    ("within 1%", "±1% of source"),
    ("+/- 0.5 percent", "±0.5% of source"),
    ("within 0.01", "absolute ±0.01"),
    ("within 0.005", "absolute ±0.005"),
    ("within $1,000", "absolute ±1,000.00"),
    ("", "exact"),
    (None, "exact"),
    ("exact match", "exact"),
    ("Ignore case", "exact, ignoring case"),
    ("ignore spaces", "exact, ignoring spaces"),
    ("same date, ignore time", "same date, time ignored"),
])
def test_rule_preview(text, preview):
    from core.rules import rule_preview
    assert rule_preview(text) == preview


def test_rule_preview_flags_unrecognised_rules():
    from core.rules import rule_preview
    assert rule_preview("roughly the same").startswith("⚠ not understood")


def test_preview_column_tracks_rule_edits():
    import pandas as pd
    from core.templates import PREVIEW_COL, RULE_COL, preview_is_stale, with_rule_preview

    grid = with_rule_preview(pd.DataFrame({"File 1 Column": ["AMT", "STATUS"], "File 2 Column": ["AMT", "STATUS"],
                                           RULE_COL: ["within 1%", None]}))
    assert list(grid[PREVIEW_COL]) == ["±1% of source", "exact"]
    assert not preview_is_stale(grid)

    grid.loc[0, RULE_COL] = "within 1"         # user edits the rule in the grid
    assert preview_is_stale(grid)
    assert list(with_rule_preview(grid)[PREVIEW_COL]) == ["absolute ±1.00", "exact"]

    grid.loc[2] = ["NEW", "NEW", None, None]   # a newly added row with no rule yet
    assert preview_is_stale(grid)
