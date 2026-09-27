import json
from typing import List, Optional, Tuple

from litellm import completion, get_llm_provider
from pydantic import ValidationError

from core.rules import RuleSpec, parse_rule
from core.schemas import ValidationConfig


# Providers where temperature=0 and native JSON mode are safe to send. Claude 5 models reject
# sampling parameters, OpenAI's GPT-5 reasoning models only accept the default temperature, and
# LiteLLM emulates JSON mode on Anthropic with a forced tool call that newer Claude models reject.
# Every response is validated anyway, so omitting these only costs a little determinism.
TEMPERATURE_PROVIDERS = {"gemini", "mistral", "groq", "cohere_chat", "cohere"}
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
