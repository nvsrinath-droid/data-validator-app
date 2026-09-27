"""Command-line reconciliation.

    python main.py source.csv target.csv --config config.json
    python main.py source.csv target.csv --model anthropic/claude-opus-5 --auto   # AI-suggested mapping
    python main.py big_source.csv big_target.csv --config config.json --engine duckdb

Exits 0 when the files reconcile, 1 when exceptions were found, 2 on errors, so it can gate a pipeline.
"""
import argparse
import json
import os
import sys

from dotenv import load_dotenv

from ai.agent import AIAgent, provider_of, resolve_rules
from connectors.file_connector import FileConnector
from core.reporter import Reporter
from core.schemas import ValidationConfig
from core.sources import ConnectorPair, FilePair

PROVIDER_KEY_VARS = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
                     "groq": "GROQ_API_KEY", "mistral": "MISTRAL_API_KEY", "cohere_chat": "COHERE_API_KEY",
                     "cohere": "COHERE_API_KEY"}


def api_key_for(model: str) -> str:
    return os.environ.get(PROVIDER_KEY_VARS.get(provider_of(model), ""), "")


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="TrueAlign data reconciliation (CLI)")
    parser.add_argument("file1", help="Path to the source file (system of record)")
    parser.add_argument("file2", help="Path to the target file to compare")
    parser.add_argument("--config", help="Path to a config JSON (skips the AI mapping step)")
    parser.add_argument("--engine", choices=["pandas", "duckdb"], default="pandas",
                        help="pandas (in memory) or duckdb (large files, streamed from disk)")
    parser.add_argument("--model", default=os.environ.get("TRUEALIGN_MODEL", "gemini/gemini-3.8-flash"),
                        help="LiteLLM model string for AI mapping / rule interpretation")
    parser.add_argument("--api-key", help="API key for --model (default: the provider's *_API_KEY env var)")
    parser.add_argument("--auto", action="store_true", help="Accept the AI-suggested mapping without prompting")
    parser.add_argument("--output", default="output", help="Directory for the reports")
    args = parser.parse_args()

    pair = (FilePair(args.file1, args.file2) if args.engine == "duckdb"
            else ConnectorPair(FileConnector(args.file1), FileConnector(args.file2)))
    api_key = args.api_key or api_key_for(args.model)
    agent = AIAgent(args.model, api_key) if api_key else None

    if args.config:
        with open(args.config, encoding="utf-8") as f:
            config = ValidationConfig(**json.load(f))
    else:
        if agent is None:
            print(f"No API key for {args.model}. Pass --api-key, set the provider's *_API_KEY, or use --config.")
            return 2
        print(f"Requesting a mapping from {args.model}...")
        try:
            config = agent.suggest_configuration(pair.sample("source").to_csv(index=False),
                                                 pair.sample("target").to_csv(index=False))
        except Exception as e:
            print(f"Failed to generate configuration from AI: {e}")
            return 2
        print(config.model_dump_json(indent=2, exclude_none=True))
        if not args.auto:
            answer = input("Accept this configuration? (y/n/edit): ").strip().lower()
            if answer == "edit":
                with open("temp_config.json", "w", encoding="utf-8") as f:
                    f.write(config.model_dump_json(indent=2, exclude_none=True))
                print(f"Saved to temp_config.json. Edit it, then run:\n"
                      f"  python main.py {args.file1} {args.file2} --config temp_config.json")
                return 0
            if answer != "y":
                print("Aborting.")
                return 0

    config, notes = resolve_rules(config, agent)
    print(f"Running the {args.engine} engine...")
    try:
        result = pair.run(config)
    except ValueError as e:
        print(f"Configuration error: {e}")
        return 2
    result.warnings[:0] = notes

    reporter = Reporter(args.output)
    paths = [reporter.generate_json_report(result), reporter.generate_excel_report(result),
             *reporter.generate_csv_reports(result)]

    print("\n----- Validation Summary -----")
    print(f"Source rows:              {result.total_source:,}")
    print(f"Target rows:              {result.total_target:,}")
    print(f"Matched rows:             {result.matched_rows:,}")
    print(f"Mismatched rows:          {result.mismatched_rows:,}")
    print(f"Missing in target:        {result.missing_in_target_count:,}")
    print(f"Missing in source:        {result.missing_in_source_count:,}")
    print(f"Duplicate keys:           {result.duplicate_key_count:,}")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    print("\nReports:\n  " + "\n  ".join(paths))

    if not result.has_exceptions:
        print("\nSUCCESS! Source and target reconcile based on the configuration.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
