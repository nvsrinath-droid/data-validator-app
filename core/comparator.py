import pandas as pd
import numpy as np
from typing import Dict, Any, List
from .schemas import ValidationConfig

class DataComparator:
    """Core logic engine for comparing two DataFrames."""
    
    def __init__(self, config: ValidationConfig, rule_code: str = None):
        self.config = config
        self.rule_code = rule_code
        self.evaluate_rules_func = None
        
        if self.rule_code:
            # Safely compile the AI generated function string into an actual python function
            local_vars = {}
            try:
                # Provide pandas to the local namespace the AI might use
                exec_globals = {"pd": pd, "np": np}
                exec(self.rule_code, exec_globals, local_vars)
                self.evaluate_rules_func = local_vars.get('evaluate_rules')
            except Exception as e:
                print(f"Error compiling AI validation rules: {e}")

    def compare(self, df1: pd.DataFrame, df2: pd.DataFrame) -> Dict[str, Any]:
        """
        Main comparison method. 
        Takes the File 1 (source of truth) and File 2 (external file).
        """
        # 1. Standardize columns based on mapping
        # We rename File 2 columns so they match File 1
        rename_map = {m.file2_column: m.file1_column for m in self.config.column_mappings}
        df2_renamed = df2.rename(columns=rename_map)
        
        # 2. Filter down to only the columns we care about in both
        # The columns we care about are the keys in our column_mapping dictionary
        target_cols = [m.file1_column for m in self.config.column_mappings]
        
        # Ensure our primary keys are in our target cols
        for pk in self.config.primary_keys:
            if pk not in target_cols:
                target_cols.append(pk)
                
        # Remove ignore columns from our target cols
        if self.config.ignore_columns:
             target_cols = [c for c in target_cols if c not in self.config.ignore_columns]
             
        # Select the columns (ignoring any that don't exist in the df to prevent KeyError)
        cols_to_keep_df1 = [c for c in target_cols if c in df1.columns]
        cols_to_keep_df2 = [c for c in target_cols if c in df2_renamed.columns]
        
        df1_subset = df1[cols_to_keep_df1].copy()
        df2_subset = df2_renamed[cols_to_keep_df2].copy()

        # 3. Outer Join the two DataFrames on the primary key(s)
        # Using indicator=True so we know which side the row came from
        merged_df = pd.merge(
            df1_subset, 
            df2_subset, 
            on=self.config.primary_keys, 
            how='outer', 
            indicator=True,
            suffixes=('_f1', '_f2')
        )
        
        results = {
            "missing_in_file1": [],
            "missing_in_file2": [],
            "mismatches": []
        }
        
        # 4. Identify Missing Rows
        # Rows only in right (File 2)
        missing_in_f1_mask = merged_df['_merge'] == 'right_only'
        if missing_in_f1_mask.any():
            # Grab the rows and keep only the F2 columns, strip the suffix for clean reporting
            missing_df = merged_df[missing_in_f1_mask].copy()
            clean_cols = [c for c in missing_df.columns if c.endswith('_f2') or c in self.config.primary_keys]
            missing_df = missing_df[clean_cols]
            missing_df.columns = [c.replace('_f2', '') for c in missing_df.columns]
            results["missing_in_file1"] = missing_df.to_dict(orient='records')
            
        # Rows only in left (File 1)
        missing_in_f2_mask = merged_df['_merge'] == 'left_only'
        if missing_in_f2_mask.any():
            missing_df = merged_df[missing_in_f2_mask].copy()
            clean_cols = [c for c in missing_df.columns if c.endswith('_f1') or c in self.config.primary_keys]
            missing_df = missing_df[clean_cols]
            missing_df.columns = [c.replace('_f1', '') for c in missing_df.columns]
            results["missing_in_file2"] = missing_df.to_dict(orient='records')

        # 5. Identify Value Mismatches
        # For rows that exist in both files, compare the columns
        both_mask = merged_df['_merge'] == 'both'
        if both_mask.any():
            both_df = merged_df[both_mask]
            
            # Figure out which columns we actually need to compare
            # They must end in _f1, have a corresponding _f2, and not be a primary key
            cols_to_compare = [c.replace('_f1', '') for c in both_df.columns if c.endswith('_f1') and f"{c.replace('_f1', '')}_f2" in both_df.columns]

            # Build a dictionary to check which columns have rules and which should fall back to exact match
            mapped_cols_with_rules = {m.file1_column: m.validation_rule for m in self.config.column_mappings if m.validation_rule}

            for index, row in both_df.iterrows():
                row_mismatches = []
                
                # Check column by column
                for col in cols_to_compare:
                    val1 = row[f"{col}_f1"]
                    val2 = row[f"{col}_f2"]
                    
                    # If this specific column has an AI validation rule, we skip exact matching for this column.
                    # It will be evaluated in the AI function below.
                    if col in mapped_cols_with_rules:
                        continue 
                        
                    # Default Exact Match Logic (if no rule is specified)
                    if pd.isna(val1) and pd.isna(val2):
                        continue
                    
                    if val1 != val2:
                        row_mismatches.append({
                            "column": col,
                            "file1_value": val1,
                            "file2_value": val2,
                            "error": "Exact match failed"
                        })
                
                # Check AI-generated Validation Rules across the entire row
                if self.evaluate_rules_func:
                    try:
                        rule_errors = self.evaluate_rules_func(row)
                        if rule_errors and isinstance(rule_errors, list):
                            # Add these AI errors into the mismatch report
                            for err_msg in rule_errors:
                                # We try to extract the column name from the error, or just dump it
                                row_mismatches.append({
                                    "column": "Rule Violation",
                                    "file1_value": "N/A",
                                    "file2_value": "N/A",
                                    "error": err_msg
                                })
                    except Exception as e:
                        row_mismatches.append({
                            "column": "Rule Execution Error",
                            "file1_value": "Error",
                            "file2_value": "Error",
                            "error": str(e)
                        })

                # If we found any mismatches for this row (either exact match or rule based), add it to our report
                if row_mismatches:
                    pk_values = {pk: row[pk] for pk in self.config.primary_keys}
                    results["mismatches"].append({
                        "primary_keys": pk_values,
                        "differences": row_mismatches
                    })

        return results
