import os
from google import genai
from google.genai import types
import json
from core.schemas import ValidationConfig

class GeminiAgent:
    """Interacts with the Gemini API to suggest configurations."""
    
    def __init__(self, api_key: str = None):
        if not api_key:
            api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("Gemini API key is required. Set it in .env or pass it directly.")
        
        # Initialize the new genai client
        self.client = genai.Client(api_key=api_key)
        self.model_name = 'gemini-2.5-flash'
        
    def suggest_configuration(self, file1_sample: str, file2_sample: str) -> ValidationConfig:
        """
        Takes string representations of the file samples and uses Gemini to 
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

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ValidationConfig,
                temperature=0.1
            ),
        )

        # Parse the response into our Pydantic model
        config_data = json.loads(response.text)
        return ValidationConfig(**config_data)

    def generate_rule_evaluator_code(self, rules_dict: dict) -> str:
        """
        Takes a dictionary mapping column names to plain English validation rules.
        Uses Gemini to generate a Python function `def evaluate_rules(row):` that 
        takes a Pandas Row and returns a list of error strings (or empty list if passed).
        """
        prompt = f"""
        You are an expert Python data engineer. I have a pandas dataframe containing data from two different files.
        For a given row, the data from File 1 is accessed via `row['ColumnName_f1']` and File 2 via `row['ColumnName_f2']`.
        
        The user has provided the following plain-English validation rules for specific columns:
        {json.dumps(rules_dict, indent=2)}
        
        Write a robust Python function named `evaluate_rules(row)` that executes these rules.
        - Handle NaN or Null values gracefully (e.g., using `pd.isna()`).
        - The function must return a list of error message strings. If all rules pass, return an empty list `[]`.
        - Format the error message like: "ColumnName rule Failed: Expected X but got Y".
        - Do not include any explanations, imports, or markdown formatting like ```python. Just the raw python code.
        """

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
        )

        code = response.text.strip()
        if code.startswith("```python"):
            code = code[9:]
        if code.startswith("```"):
            code = code[3:]
        if code.endswith("```"):
            code = code[:-3]
            
        return code.strip()
