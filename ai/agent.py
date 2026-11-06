import json
import warnings
from typing import List, Optional, Tuple

from litellm import completion, get_llm_provider
from pydantic import TypeAdapter, ValidationError

from ai.quality_summary import ColumnAliases, profile_summary, result_summary
from core.normalize import Kind
from core.quality.profile import TableProfile
from core.quality.specs import CheckSpec, Freshness, Outliers, QualityResult, RefIntegrity
from core.rules import RuleSpec, parse_rule
from core.schemas import ValidationConfig

def silence_litellm_serializer_warning() -> None:
    """LiteLLM dumps its own response objects with pydantic after every call, and pydantic reports "Pydantic
    serializer warnings ... serialized value may not be as expected" for them. It is noise from inside LiteLLM
    (we never serialise those objects), and it lands in the user's console once per call. Only that message is
    ignored. A process-wide filter, not catch_warnings(), because catch_warnings is not thread-safe and Streamlit
    runs one thread per session. Idempotent: warnings.filterwarnings replaces an identical filter."""
    warnings.filterwarnings("ignore", message=r"Pydantic serializer warnings", category=UserWarning)


silence_litellm_serializer_warning()
MAX_SUGGESTED_CHECKS = 50
_CHECK_ADAPTER = TypeAdapter(CheckSpec)


# Providers where temperature=0 and native JSON mode are safe to send. Claude 5 models reject
# sampling parameters, OpenAI's GPT-5 reasoning models only accept the default temperature, and
# LiteLLM emulates JSON mode on Anthropic with a forced tool call that newer Claude models reject.
# Every response is validated anyway, so omitting these only costs a little determinism.
TEMPERATURE_PROVIDERS = {"gemini", "mistral", "groq", "cohere_chat", "cohere", "deepseek"}
JSON_MODE_PROVIDERS = {"gemini", "mistral", "groq", "openai"}


def provider_of(model: str) -> str:
    try:
        return get_llm_provider(model)[1]
    except Exception:
        return model.split("/", 1)[0] if "/" in model else ""


def _strip_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


class AIAgent:
    """Interacts with various LLM providers (Google, OpenAI, Anthropic, etc.) via LiteLLM.

    The API key is held on the instance and passed to every completion() call. It is
    never written to os.environ, which is shared by every user of a Streamlit server.
    """

    def __init__(self, model_name: str, api_key: str):
        """
        Args:
            model_name: The LiteLLM model string (e.g., 'anthropic/claude-opus-5', 'gemini/gemini-3.8-flash')
            api_key: The API key for the respective provider.
        """
        self.model_name = model_name
        self.api_key = api_key

    def _call_llm(self, prompt: str, is_json: bool = False) -> str:
        kwargs = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "api_key": self.api_key,
        }
        provider = provider_of(self.model_name)
        if provider in TEMPERATURE_PROVIDERS:
            kwargs["temperature"] = 0
        if is_json and provider in JSON_MODE_PROVIDERS:
            kwargs["response_format"] = {"type": "json_object"}
        silence_litellm_serializer_warning()   # a test runner or library may have reset the filters since import
        try:
            response = completion(**kwargs)
            return response.choices[0].message.content
        except Exception as e:
            message = str(e)
            if self.api_key:
                message = message.replace(self.api_key, "***")
            raise RuntimeError(f"LLM Provider Error: {message}") from None

    def suggest_configuration(self, file1_sample: str, file2_sample: str) -> ValidationConfig:
        """
        Takes string representations of the file samples and uses the LLM to
        suggest a configuration schema mapping the files.
        """
        prompt = f"""
        You are an expert data analyst AI. Let's build a data validation agent.
        I want to compare two source files (File 1 and File 2) for missing rows and mismatched values.

        Here is a sample of File 1 (the source of truth):
        {file1_sample}

        Here is a sample of File 2 (the external file):
        {file2_sample}

        Please analyze these samples and suggest a configuration.
        1. Identify the logical Primary Key(s) to join these datasets. If one file has a column like 'EmpID' and the other has 'Employee Identifier', those should be the primary keys.
        2. Create a column mapping dictionary where the keys are the column names in File 1, and the values are the corresponding column names in File 2.

        Respond ONLY with a valid JSON object matching this schema:
        {{
            "primary_keys": ["KeyColNameOnFile1"],
            "column_mappings": [{{"file1_column": "File1ColA", "file2_column": "File2ColA"}}]
        }}
        """
        response_text = self._call_llm(prompt, is_json=True)
        try:
            data = json.loads(_strip_fences(response_text))
            # Only accept the fields we asked for; the model doesn't get to set rule specs.
            return ValidationConfig(
                primary_keys=data.get("primary_keys", []),
                column_mappings=[{"file1_column": m["file1_column"], "file2_column": m["file2_column"]}
                                 for m in data.get("column_mappings", [])],
            )
        except Exception as e:
            raise ValueError(f"Failed to parse LLM JSON mapping: {e}\nRaw Response: {response_text}")

    def interpret_rule(self, rule_text: str, source_column: str, target_column: str) -> RuleSpec:
        """Translate a plain-English rule into a RuleSpec.

        The model only chooses from a fixed set of rule kinds and a tolerance; the
        result is validated by pydantic (unknown kinds and extra fields are rejected).
        Nothing the model returns is ever executed.
        """
        prompt = f"""
        Translate a data-reconciliation rule into JSON. The rule compares column "{source_column}"
        (source) with column "{target_column}" (target).

        Rule: {json.dumps(rule_text)}

        Choose exactly one "kind":
          "exact"             - values must be equal
          "abs_tolerance"     - numbers may differ by at most "tolerance" (absolute)
          "pct_tolerance"     - numbers may differ by at most "tolerance" percent of the source value
          "ignore_case"       - text equal ignoring upper/lower case
          "ignore_whitespace" - text equal ignoring spaces
          "date_only"         - same calendar date, time of day ignored
          "unsupported"       - none of the above can express the rule

        Respond ONLY with JSON: {{"kind": "...", "tolerance": <number or null>}}
        """
        data = json.loads(_strip_fences(self._call_llm(prompt, is_json=True)))
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
        if data.get("kind") == "unsupported":
            raise ValueError("The model could not express this rule with the supported rule kinds")
        return RuleSpec.model_validate(data)  # extra="forbid": any unexpected field is rejected


    # ---- data quality (summaries only; see ai/quality_summary.py) -----------------------

    def suggest_checks(self, profile: TableProfile, references: Optional[List[str]] = None,
                       include_extremes: bool = False, hide_column_names: bool = False) -> Tuple[list, List[str]]:
        """Suggest quality checks from a column profile. Returns (checks, notes about dropped suggestions).

        The model sees only the profile summary. Each suggestion is validated as a closed-set CheckSpec
        and checked against the real columns and the offered reference names; anything else is dropped.
        """
        references = list(references or [])
        aliases = ColumnAliases([c.name for c in profile.columns], hide_column_names)
        summary = profile_summary(profile, include_extremes, hide_column_names, aliases)
        prompt = f"""
        You are a data quality engineer. Below is a statistical summary of one table (no row values).

        {json.dumps(summary)}

        Suggest data quality checks. Use ONLY these check types (JSON objects):
          {{"type": "null_rate", "column": C, "max_pct": 0-100}}
          {{"type": "distinct", "column": C, "unique": true|false, "min_distinct": int|null, "max_distinct": int|null}}
          {{"type": "type_drift", "column": C, "expected": "numeric"|"date"|"string", "max_pct": 0-100}}
          {{"type": "freshness", "column": C, "max_age": "<number><m|h|d>"}}   (date columns only)
          {{"type": "ref_integrity", "column": C, "ref_name": R, "ref_column": RC, "max_orphans": int}}
          {{"type": "outliers", "column": C, "method": "iqr"|"zscore", "k": number|null, "max_count": int}}  (numeric columns only; prefer "zscore"
          for columns where more than half the values are equal, because "iqr" is inconclusive there)
        Every check may also set "severity": "fail" or "warn". C must be a column name from the summary.
        Reference tables you may use for ref_integrity: {json.dumps(references)} (you do not know their columns; omit
        ref_integrity unless you are confident of ref_column).

        Respond ONLY with JSON: {{"checks": [ ... ]}}
        """
        text = self._call_llm(prompt, is_json=True)
        try:
            data = json.loads(_strip_fences(text))
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse LLM JSON checks: {e}") from None
        raw = data.get("checks") if isinstance(data, dict) else data
        if not isinstance(raw, list):
            raise ValueError("Expected a JSON object with a 'checks' list")

        columns = {c.name: c for c in profile.columns}
        checks, notes = [], []
        for item in raw[:MAX_SUGGESTED_CHECKS]:
            try:
                spec = _CHECK_ADAPTER.validate_python(item)
            except ValidationError as e:
                notes.append(f"Dropped an invalid suggestion ({e.errors()[0]['msg']}).")
                continue
            except (ValueError, TypeError, OverflowError) as e:  # a bad suggestion must never abort the rest
                notes.append(f"Dropped an invalid suggestion ({type(e).__name__}).")
                continue
            real = aliases.restore(spec.column)          # placeholders (col_3) map back to real names locally
            col = columns.get(real) if real is not None else None
            if col is not None and real != spec.column:
                spec = spec.model_copy(update={"column": real})
            if col is None:
                notes.append(f"Dropped {spec.type} on unknown column {spec.column!r}.")
            elif isinstance(spec, Outliers) and col.kind != Kind.NUMERIC:
                notes.append(f"Dropped outliers on non-numeric column {spec.column!r}.")
            elif isinstance(spec, Freshness) and col.kind != Kind.DATE:
                notes.append(f"Dropped freshness on non-date column {spec.column!r}.")
            elif isinstance(spec, RefIntegrity) and spec.ref_name not in references:
                notes.append(f"Dropped ref_integrity against unknown reference {spec.ref_name!r}.")
            else:
                checks.append(spec)
        if len(raw) > MAX_SUGGESTED_CHECKS:
            notes.append(f"Ignored {len(raw) - MAX_SUGGESTED_CHECKS} suggestions beyond the first {MAX_SUGGESTED_CHECKS}.")
        return checks, notes

    def explain_results(self, result: QualityResult, include_extremes: bool = False,
                        hide_column_names: bool = False) -> str:
        """Plain-English triage of a quality run. The model sees check parameters and counts, never data."""
        prompt = f"""
        You are a data quality engineer. Here are the results of data quality checks on one table.
        You only have counts and thresholds, not the data itself.

        {json.dumps(result_summary(result, include_extremes, hide_column_names))}

        In plain English: say what failed or warned and by how much, what the likely causes are, and what to
        look at first. Do not invent values or column contents. Be concise.
        """
        return (self._call_llm(prompt) or "").strip()


def resolve_rules(config: ValidationConfig, agent: Optional[AIAgent]) -> Tuple[ValidationConfig, List[str]]:
    """Fill in rule_spec for rules the deterministic parser can't read, using the AI.

    Returns the updated config and human-readable notes. Rules the AI can't express
    (or returns invalid output for) are left for the engines, which fall back to exact
    match and warn.
    """
    notes: List[str] = []
    mappings = []
    for m in config.column_mappings:
        if m.rule_spec is None and m.validation_rule:
            _, warning = parse_rule(m.validation_rule)
            if warning and agent is not None:
                try:
                    spec = agent.interpret_rule(m.validation_rule, m.file1_column, m.file2_column)
                    m = m.model_copy(update={"rule_spec": spec})
                    notes.append(f"{m.file1_column}: AI interpreted '{m.validation_rule}' as {spec.describe()}.")
                except (ValueError, ValidationError, RuntimeError, json.JSONDecodeError) as e:
                    notes.append(f"{m.file1_column}: AI could not interpret '{m.validation_rule}' ({e}).")
        mappings.append(m)
    return config.model_copy(update={"column_mappings": mappings}), notes
