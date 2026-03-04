import pandas as pd
import duckdb
from typing import List, Dict, Optional
import json

from core.schemas import ValidationConfig

class DuckDBEngine:
    """
    Executes data validation directly on massive flat-files using DuckDB's fast SQL engine,
    bypassing Pandas memory limits. Translates AI Rules into SQL CASE statements.
    """
    def __init__(self, config: ValidationConfig, rules_dict: Optional[Dict[str, str]] = None):
        self.config = config
        self.rules_dict = rules_dict or {}

    def _translate_rule_to_sql(self, column: str, rule: str) -> str:
        """
        Translates a plain-English rule into a SQL condition for DuckDB.
        WARNING: This is a simplictic static parser for rapid fallback. 
        In Phase 6, we will route this to litellm to generate complex SQL snippets.
        """
        rule_lower = rule.lower()
        col1 = f"f1.\"{column}\""
        col2 = f"f2.\"{column}\""
        
        if "tolerance" in rule_lower or "+/-" in rule_lower or "within" in rule_lower:
            # Extract numbers blindly for simple tolerance
            numbers = [int(s) for s in rule_lower.replace('$', '').replace('%', '').split() if s.isdigit()]
            if numbers:
                tol = numbers[0]
                if "%" in rule_lower:
                    return f"ABS(CAST({col1} AS DOUBLE) - CAST({col2} AS DOUBLE)) <= (CAST({col1} AS DOUBLE) * {tol} / 100.0)"
                return f"ABS(CAST({col1} AS DOUBLE) - CAST({col2} AS DOUBLE)) <= {tol}"
                
        if "ignore case" in rule_lower or "case insensitive" in rule_lower:
            return f"LOWER(CAST({col1} AS VARCHAR)) = LOWER(CAST({col2} AS VARCHAR))"
            
        # Default strict fallback if rule isn't understood
        return f"CAST({col1} AS VARCHAR) = CAST({col2} AS VARCHAR)"

    def compare(self, file1_path: str, file2_path: str) -> dict:
        """
        Executes a massive outer join directly on the CSV files using DuckDB.
        Returns a dictionary of dataframes identical to the Pandas DataComparator for UI compatibility.
        """
        conn = duckdb.connect(database=':memory:')
        
        # 1. Register the files as tables
        conn.execute(f"CREATE TABLE file1 AS SELECT * FROM read_csv_auto('{file1_path}')")
        conn.execute(f"CREATE TABLE file2 AS SELECT * FROM read_csv_auto('{file2_path}')")
        
        # 2. Build the JOIN condition from Primary Keys
        join_conditions = []
        for pk in self.config.primary_keys:
            join_conditions.append(f"f1.\"{pk}\" = f2.\"{pk}\"")
        join_clause = " AND ".join(join_conditions)
        
        # 3. Build the Validation Conditions (Exact Match OR AI Rule Match)
        validation_checks = []
        select_cols = [f"COALESCE(f1.\"{pk}\", f2.\"{pk}\") AS \"{pk}\"" for pk in self.config.primary_keys]
        
        for mapping in self.config.column_mappings:
            c1 = mapping.file1_column
            c2 = mapping.file2_column
            
            # Select both columns so the user can see what mismatched
            select_cols.append(f"f1.\"{c1}\" AS \"File1_{c1}\"")
            select_cols.append(f"f2.\"{c2}\" AS \"File2_{c2}\"")
            
            # Did they provide an AI Rule?
            rule = None
            if mapping.validation_rule:
                rule = mapping.validation_rule
            elif self.rules_dict.get(c1):
                rule = self.rules_dict.get(c1)
                
            if rule:
                sql_condition = self._translate_rule_to_sql(c1, rule)
                # Output a 'Pass/Fail' boolean column for the UI to read
                select_cols.append(f"CASE WHEN {sql_condition} THEN TRUE ELSE FALSE END AS \"{c1}_IsValid\"")
            else:
                # Standard Exact Match
                select_cols.append(f"CASE WHEN CAST(f1.\"{c1}\" AS VARCHAR) = CAST(f2.\"{c2}\" AS VARCHAR) THEN TRUE ELSE FALSE END AS \"{c1}_IsValid\"")
        
        select_clause = ",\n    ".join(select_cols)
        
        # --- EXECUTE THE MASSIVE QUERY ---
        # The FULL OUTER JOIN guarantees we catch Missing in File 1 and Missing in File 2
        query = f"""
        SELECT 
            {select_clause}
        FROM file1 f1
        FULL OUTER JOIN file2 f2 
        ON {join_clause}
        """
        
        merged_df = conn.execute(query).df()
        
        # --- POST-PROCESSING FOR STREAMLIT UI ---
        # We need to slice the results into the standard buckets: Match, Mismatch, Missing1, Missing2
        results = {
            "Total Rows File 1": conn.execute("SELECT COUNT(*) FROM file1").fetchone()[0],
            "Total Rows File 2": conn.execute("SELECT COUNT(*) FROM file2").fetchone()[0],
            "Missing in File 1 (Found in 2)": pd.DataFrame(),
            "Missing in File 2 (Found in 1)": pd.DataFrame(),
            "Data Mismatches": pd.DataFrame(),
            "Exact Matches": pd.DataFrame(),
            "Mismatch Breakdown": []
        }
        
        # Detect completely missing rows (Primary Key is null on one side)
        # We check the first primary key's raw value from the SELECT aliases
        first_pk = self.config.primary_keys[0]
        f1_pk_missing = merged_df[f"File1_{first_pk}"].isna() if f"File1_{first_pk}" in merged_df else pd.Series(False, index=merged_df.index)
        f2_pk_missing = merged_df[f"File2_{first_pk}"].isna() if f"File2_{first_pk}" in merged_df else pd.Series(False, index=merged_df.index)
        
        # *Note*: DuckDB COALESCE puts the surviving PK in the base column name
        missing_in_1 = merged_df[f1_pk_missing & ~f2_pk_missing]
        missing_in_2 = merged_df[f2_pk_missing & ~f1_pk_missing]
        
        results["Missing in File 1 (Found in 2)"] = missing_in_1.copy()
        results["Missing in File 2 (Found in 1)"] = missing_in_2.copy()
        
        # Both exist -> Let's check Validation Columns
        matched_pk_df = merged_df[~f1_pk_missing & ~f2_pk_missing]
        
        if not matched_pk_df.empty:
            # A row is a mismatch if ANY of the `_IsValid` columns are False
            is_valid_cols = [c for c in matched_pk_df.columns if c.endswith("_IsValid")]
            
            # If all are true -> Exact Match
            all_valid_mask = matched_pk_df[is_valid_cols].all(axis=1)
            results["Exact Matches"] = matched_pk_df[all_valid_mask].copy()
            
            # If any are false -> Data Mismatch
            mismatch_df = matched_pk_df[~all_valid_mask].copy()
            results["Data Mismatches"] = mismatch_df
            
            # Build the detailed breakdown for the UI exactly like Pandas does
            breakdown = []
            for _, row in mismatch_df.iterrows():
                for c1_col in [m.file1_column for m in self.config.column_mappings]:
                    is_valid_col = f"{c1_col}_IsValid"
                    if is_valid_col in row and not row[is_valid_col]:
                        # Find the corresponding Map to get the rule and File 2 column name
                        mapping = next((m for m in self.config.column_mappings if m.file1_column == c1_col), None)
                        c2_col = mapping.file2_column if mapping else c1_col
                        rule = mapping.validation_rule if mapping else ""
                        
                        pk_display = ", ".join([f"{pk}={row[pk]}" for pk in self.config.primary_keys])
                        breakdown.append({
                            "Primary Key": pk_display,
                            "Column": f"{c1_col} -> {c2_col}",
                            "File 1 Value": row[f"File1_{c1_col}"],
                            "File 2 Value": row[f"File2_{c2_col}"],
                            "Validation Rule": rule,
                            "Remarks": f"Failed Rule: {rule}" if rule else "Exact Match Failed"
                        })
            
            results["Mismatch Breakdown"] = breakdown
            
        return results
