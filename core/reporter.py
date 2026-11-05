import io
import json
import os

import pandas as pd

from .results import ComparisonResult


def result_sheets(result: ComparisonResult) -> dict:
    """Sheet name -> DataFrame for every section of a result."""
    summary = pd.DataFrame([
        ("Source rows", result.total_source),
        ("Target rows", result.total_target),
        ("Matched rows", result.matched_rows),
        ("Mismatched rows", result.mismatched_rows),
        ("Missing in target (source only)", result.missing_in_target_count),
        ("Missing in source (target only)", result.missing_in_source_count),
        ("Duplicate keys", result.duplicate_key_count),
    ] + [(f"Mismatches: {col}", n) for col, n in result.mismatches_by_column.items()],
        columns=["Metric", "Value"])
    sheets = {
        "Summary": summary,
        "Mismatches": result.mismatches,
        "Missing in Target": result.missing_in_target,
        "Missing in Source": result.missing_in_source,
        "Duplicate Keys": result.duplicate_keys,
    }
    if result.warnings:
        sheets["Warnings"] = pd.DataFrame({"Warning": result.warnings})
    return sheets


def excel_report(result: ComparisonResult) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, frame in result_sheets(result).items():
            frame.to_excel(writer, sheet_name=name[:31], index=False)
    return buffer.getvalue()


class Reporter:
    """Writes comparison results to disk (used by the CLI)."""

    def __init__(self, output_dir: str = "output"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate_json_report(self, result: ComparisonResult, filename: str = "validation_report.json") -> str:
        path = os.path.join(self.output_dir, filename)
        payload = {name: json.loads(frame.to_json(orient="records", date_format="iso"))
                   for name, frame in result_sheets(result).items()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        return path

    def generate_csv_reports(self, result: ComparisonResult, prefix: str = "report") -> list:
        paths = []
        for name, frame in result_sheets(result).items():
            if frame.empty:
                continue
            path = os.path.join(self.output_dir, f"{prefix}_{name.lower().replace(' ', '_')}.csv")
            frame.to_csv(path, index=False)
            paths.append(path)
        return paths

    def generate_excel_report(self, result: ComparisonResult, filename: str = "validation_report.xlsx") -> str:
        path = os.path.join(self.output_dir, filename)
        with open(path, "wb") as f:
            f.write(excel_report(result))
        return path
