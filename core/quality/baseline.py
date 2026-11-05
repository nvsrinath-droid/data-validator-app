"""Saved profile baselines and profile-to-profile drift.

A baseline is a TableProfile saved as JSON. It holds column names, kinds, counts and (for numeric/date
columns) min/max, so treat it as data: keep it outside the repository. `*.baseline.json` is git-ignored
as a safety net, but the path is always chosen by the caller.
"""
from pathlib import Path
from typing import List

from .profile import TableProfile

# A column whose null rate rises by more than this many percentage points is reported as drift.
NULL_PCT_DELTA = 10.0


def save_baseline(profile: TableProfile, path: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(profile.to_json(), encoding="utf-8")


def load_baseline(path: str) -> TableProfile:
    return TableProfile.from_json(Path(path).read_text(encoding="utf-8"))


def compare_profiles(baseline: TableProfile, current: TableProfile, null_pct_delta: float = NULL_PCT_DELTA) -> List[str]:
    """Human-readable differences between a saved baseline and the current profile."""
    old = {c.name: c for c in baseline.columns}
    new = {c.name: c for c in current.columns}
    findings = [f"Column {n!r} was in the baseline but is missing now." for n in old if n not in new]
    findings += [f"Column {n!r} is new since the baseline." for n in new if n not in old]
    for name in old.keys() & new.keys():
        before, after = old[name], new[name]
        if before.kind != after.kind:
            findings.append(f"Column {name!r} changed type: {before.kind.value} -> {after.kind.value}.")
        if after.null_pct - before.null_pct > null_pct_delta:
            findings.append(f"Column {name!r} null rate rose from {before.null_pct:.1f}% to {after.null_pct:.1f}%.")
    return findings
