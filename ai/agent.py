import os
import json
from litellm import completion
from core.schemas import ValidationConfig

class AIAgent:
    """Interacts with various LLM providers (Google, OpenAI, Anthropic, etc.) via LiteLLM."""
    
    def __init__(self, model_name: str, api_key: str):
        """
        Initializes the agent.
        Args:
            model_name: The LiteLLM formatted model string (e.g., 'gpt-4o', 'gemini/gemini-1.5-pro', 'claude-3-5-sonnet-20240620')
            api_key: The API key for the respective provider.
        """
        self.model_name = model_name
        self.api_key = api_key
        
        # LiteLLM routing uses environment variables under the hood for some providers
        if "gemini" in model_name.lower():
            os.environ["GEMINI_API_KEY"] = api_key
        elif "gpt" in model_name.lower() or "o1" in model_name.lower():
            os.environ["OPENAI_API_KEY"] = api_key
        elif "claude" in model_name.lower():
            os.environ["ANTHROPIC_API_KEY"] = api_key
        elif "groq" in model_name.lower():
            os.environ["GROQ_API_KEY"] = api_key
            
    def _call_llm(self, prompt: str, schema_class=None, is_json=False) -> str:
        """Helper to call litellm with correct JSON forcing if requested."""
        messages = [{"role": "user", "content": prompt}]
        
        kwargs = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0.1,
        }
        
        # If we need structured JSON output (like the config generation)
        if is_json:
            kwargs["response_format"] = {"type": "json_object"}
            
        try:
            response = completion(**kwargs)
            return response.choices[0].message.content
        except Exception as e:
            raise RuntimeError(f"LLM Provider Error: {str(e)}")

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

        # Parse the response
        try:
            # Strip markdown block formatting if the model ignored response_format
            clean_text = response_text.strip()
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:]
            if clean_text.startswith("```"):
                clean_text = clean_text[3:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
                
            config_data = json.loads(clean_text)
            return ValidationConfig(**config_data)
        except Exception as e:
             raise ValueError(f"Failed to parse LLM JSON mapping: {str(e)}\nRaw Response: {response_text}")

    def generate_rule_evaluator_code(self, rules_dict: dict) -> str:
        """
        Takes a dictionary mapping column names to plain English validation rules.
        Uses the LLM to generate a Python function `def evaluate_rules(row):`
        """
        prompt = f"""
        You are an expert Python data engineer. I have a pandas dataframe containing data from two different files.
        For a given row, the data from File 1 is accessed via `row['ColumnName_f1']` and File 2 via `row['ColumnName_f2']`.
        
        The user has provided the following plain-English validation rules for specific columns:
        {json.dumps(rules_dict, indent=2)}
        
        Write a robust Python function named `evaluate_rules(row)` that executes these rules.
        - Handle NaN or Null values gracefully.
        - The function MUST return a list of dictionaries. If all rules pass, return an empty list `[]`.
        - Each dictionary must have exactly this format: 
          {{"column": "TheColumnName", "error": "Detailed reason it failed", "file1_value": row['TheColumnName_f1'], "file2_value": row['TheColumnName_f2']}}
        - Do not include any explanations, imports, or markdown formatting like ```python. Just the raw python code.
        """

        code = self._call_llm(prompt, is_json=False).strip()
        
        if code.startswith("```python"):
            code = code[9:]
        if code.startswith("```"):
            code = code[3:]
        if code.endswith("```"):
            code = code[:-3]
            
        return code.strip()
