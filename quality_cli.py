"""Data quality commands behind main.py (see main.py for the reconciliation CLI).

    python main.py data.csv --profile
    python main.py data.csv --suggest-checks --model anthropic/claude-opus-5 [--include-extremes]
    python main.py data.csv --quality checks.json [--ref customers=customers.csv] [--baseline b.json]
                            [--save-baseline b.json] [--as-of 2024-01-16T12:00:00] [--explain --model ...]

Exits 0 when no check failed (warnings are reported but do not fail), 1 when a check failed or errored,
2 on usage errors. Baselines hold column statistics: keep them outside the repository.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import duckdb

from ai.agent import AIAgent
from core.quality.baseline import load_baseline, save_baseline
from core.quality.engine import QualityEngine
from core.quality.profile import profile_file
from core.quality.specs import QualityConfig, QualityResult

SAMPLE_ROWS_SHOWN = 5


def parse_refs(items) -> Dict[str, str]:
    refs = {}
    for item in items or []:
        name, sep, path = item.partition("=")
        if not sep or not name or not path:
            raise ValueError(f"--ref expects NAME=PATH, got {item!r}")
        refs[name] = path
    return refs


def print_profile(profile) -> None:
    print(f"Rows: {profile.row_count:,}")
    print(f"{'Column':<28}{'Kind':<9}{'Null %':>8}{'Distinct':>10}{'Bad type':>10}")
    for c in profile.columns:
        print(f"{c.name[:27]:<28}{c.kind.value:<9}{c.null_pct:>8.2f}{c.distinct_count:>10,}{c.nonconforming_count:>10,}")


def print_result(result: QualityResult) -> None:
    icons = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "error": "ERR ", "inconclusive": "INCL"}
    print(f"\n----- Data Quality ({result.row_count:,} rows) -----")
    for r in result.results:
        print(f"[{icons[r.status]}] {r.check.label}: {r.message}")
        if r.status != "pass" and not r.sample.empty:
            print("       " + r.sample.head(SAMPLE_ROWS_SHOWN).to_string(index=False).replace("\n", "\n       "))
    for w in result.warnings:
        print(f"WARNING: {w}")
    count = {s: sum(r.status == s for r in result.results) for s in icons}
    failed = count["fail"] + count["error"]
    print(f"\n{len(result.results)} checks: {count['pass']} passed, {count['warn']} warned, "
          f"{count['inconclusive']} inconclusive, {failed} failed.")


def write_report(result: QualityResult, directory: str) -> str:
    Path(directory).mkdir(parents=True, exist_ok=True)
    path = os.path.join(directory, "quality_report.json")
    payload = {
        "row_count": result.row_count, "warnings": result.warnings,
        "results": [{"check": r.check.model_dump(mode="json"), "status": r.status, "metric": r.metric,
                     "violations": r.violations, "message": r.message,
                     "sample": json.loads(r.sample.to_json(orient="records", date_format="iso"))}
                    for r in result.results],
    }
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def quality_main(args, agent: Optional[AIAgent]) -> int:
    try:
        refs = parse_refs(args.ref)
        as_of = datetime.fromisoformat(args.as_of) if args.as_of else None
    except ValueError as e:
        print(f"Usage error: {e}")
        return 2

    if args.profile:
        try:
            print_profile(profile_file(args.file1))
        except (OSError, ValueError, duckdb.Error) as e:
            print(f"Could not read {args.file1}: {e}")
            return 2
        return 0

    if args.suggest_checks:
        if agent is None:
            print(f"No API key for {args.model}. Pass --api-key or set the provider's *_API_KEY.")
            return 2
        print(f"Requesting check suggestions from {args.model} (column statistics only; no rows are sent)...")
        try:
            checks, notes = agent.suggest_checks(profile_file(args.file1), references=list(refs),
                                                 include_extremes=args.include_extremes,
                                                 hide_column_names=args.hide_column_names)
        except Exception as e:  # file errors and provider errors alike: report, exit 2
            print(f"Failed to get suggestions: {e}")
            return 2
        for note in notes:
            print(f"NOTE: {note}")
        print(QualityConfig(checks=checks).model_dump_json(indent=2, exclude_none=True))
        return 0

    existing_baseline = bool(args.save_baseline) and Path(args.save_baseline).exists()
    if existing_baseline and not args.overwrite_baseline:
        # Checked before the run: a baseline is the reference a later run is judged against, so a stray
        # --save-baseline (or the same path as --baseline) must not silently replace it.
        print(f"Refusing to overwrite the existing baseline {args.save_baseline}. "
              f"Pass --overwrite-baseline to replace it (this only happens when no check fails and the data "
              f"has not drifted from it).")
        return 2

    try:
        config = QualityConfig.model_validate_json(Path(args.quality).read_text(encoding="utf-8"))
        baseline = load_baseline(args.baseline) if args.baseline else None
        engine = QualityEngine(config, references=refs, baseline=baseline, as_of=as_of)
        result = engine.run(args.file1)
    except (OSError, ValueError, duckdb.Error) as e:  # pydantic's ValidationError is a ValueError
        print(f"Configuration error: {e}")
        return 2

    print_result(result)
    if args.save_baseline:
        if existing_baseline and (result.has_failures or result.warnings):
            # warnings are baseline drift (a column added/removed, a type change, a jump in nulls): the same
            # signal a type_drift check reports, so a drifted run is not a good reference either.
            why = "checks failed" if result.has_failures else "the data drifted from it"
            print(f"\nKept the existing baseline {args.save_baseline}: {why}. To accept the new shape on purpose, "
                  f"delete the baseline (or run without --baseline) and save a new one.")
        else:
            save_baseline(profile_file(args.file1), args.save_baseline)
            print(f"\nSaved baseline to {args.save_baseline}")
    print(f"\nReport: {write_report(result, args.output)}")

    if args.explain:
        if agent is None:
            print(f"\nNo API key for {args.model}; skipping --explain.")
        else:
            print(f"\n----- Explanation from {args.model} (counts and thresholds only) -----")
            try:
                print(agent.explain_results(result, args.include_extremes, args.hide_column_names))
            except Exception as e:
                print(f"Could not get an explanation: {e}")
    return 1 if result.has_failures else 0
