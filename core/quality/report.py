"""Serialisable views of a QualityResult, shared by the CLI report file and the web UI downloads."""
import json
from typing import Dict

import pandas as pd

from core.quality.specs import QualityResult


def report_payload(result: QualityResult) -> Dict:
    return {
        "row_count": result.row_count, "warnings": result.warnings,
        "results": [{"check": r.check.model_dump(mode="json"), "status": r.status, "metric": r.metric,
                     "violations": r.violations, "message": r.message,
                     "sample": json.loads(r.sample.to_json(orient="records", date_format="iso"))}
                    for r in result.results],
    }


def report_json(result: QualityResult) -> str:
    return json.dumps(report_payload(result), indent=2)


FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value):
    """A text cell that a spreadsheet would run as a formula (=HYPERLINK(...), +cmd, -2+3, @SUM) gets a leading
    single quote, which makes Excel and Sheets show it as text. Headers of the uploaded file reach these cells."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def results_csv(result: QualityResult) -> str:
    frame = results_frame(result)
    return frame.apply(lambda col: col.map(csv_safe)).to_csv(index=False)


def results_frame(result: QualityResult) -> pd.DataFrame:
    """One row per check (no sample rows), for CSV."""
    return pd.DataFrame([{"check": r.check.label, "type": r.check.type, "column": r.check.column,
                          "severity": r.check.severity, "status": r.status, "metric": r.metric,
                          "violations": r.violations, "message": r.message} for r in result.results],
                        columns=["check", "type", "column", "severity", "status", "metric", "violations", "message"])
