"""The only code that turns quality data into LLM prompt input.

Prompts are built from *summaries*, never from rows:
  - a profile summary: column names, types, null %, distinct counts, row count
  - a result summary: check parameters, status, measured metric and violation count
Not sent, ever: sample rows, offending values, result messages (they can quote data, for example the
newest date), and file paths. Per-column min/max are numeric/date extremes of real data, so they are
included only when the caller opts in for that run.

What IS sent: column names and reference-table names. They are metadata, but they can be sensitive.
"""
from typing import Any, Dict

from core.quality.profile import TableProfile
from core.quality.specs import QualityResult

MAX_COLUMNS = 200


def profile_summary(profile: TableProfile, include_extremes: bool = False) -> Dict[str, Any]:
    columns = []
    for c in profile.columns[:MAX_COLUMNS]:
        entry: Dict[str, Any] = {
            "name": c.name, "type": c.db_type, "kind": c.kind.value,
            "null_pct": round(c.null_pct, 2), "distinct_count": c.distinct_count,
            "unique": c.is_unique, "nonconforming_count": c.nonconforming_count,
        }
        if include_extremes and c.min is not None:
            entry["min"], entry["max"] = c.min, c.max
        columns.append(entry)
    summary: Dict[str, Any] = {"row_count": profile.row_count, "columns": columns}
    if len(profile.columns) > MAX_COLUMNS:
        summary["columns_omitted"] = len(profile.columns) - MAX_COLUMNS
    return summary


def result_summary(result: QualityResult) -> Dict[str, Any]:
    checks = []
    for r in result.results:
        spec = r.check.model_dump(mode="json", exclude_none=True)
        checks.append({"check": spec, "status": r.status,
                       "metric": None if r.metric is None else round(r.metric, 4), "violations": r.violations})
    return {"row_count": result.row_count, "checks": checks}
