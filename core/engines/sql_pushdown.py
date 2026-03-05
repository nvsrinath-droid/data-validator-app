import pandas as pd
from sqlalchemy import create_engine, text
from typing import List, Dict, Optional

from core.schemas import ValidationConfig

class SQLPushdownEngine:
    """
    Executes data validation directly on a remote database (e.g., Snowflake, Postgres).
    Translates AI mapping rules into native SQL WHERE and CASE statements to avoid
    downloading massive datasets into RAM.
    """
    def __init__(self, config: ValidationConfig, rules_dict: Optional[Dict[str, str]] = None):
        self.config = config
        self.rules_dict = rules_dict or {}

    def _translate_rule_to_sql(self, c1_col: str, c2_col: str, rule: str) -> str:
        """
        Translates plain-English rules into native SQL conditions.
        Uses simplistic pattern matching for rapid fallback.
        """
        rule_lower = rule.lower()
        col1 = f"f1.\"{c1_col}\""
        col2 = f"f2.\"{c2_col}\""
        
        if "tolerance" in rule_lower or "+/-" in rule_lower or "within" in rule_lower:
            numbers = [int(s) for s in rule_lower.replace('$', '').replace('%', '').split() if s.isdigit()]
            if numbers:
                tol = numbers[0]
                if "%" in rule_lower:
                    return f"ABS(CAST({col1} AS FLOAT) - CAST({col2} AS FLOAT)) <= (CAST({col1} AS FLOAT) * {tol} / 100.0)"
                return f"ABS(CAST({col1} AS FLOAT) - CAST({col2} AS FLOAT)) <= {tol}"
                
        if "ignore case" in rule_lower or "case insensitive" in rule_lower:
            return f"LOWER(CAST({col1} AS VARCHAR)) = LOWER(CAST({col2} AS VARCHAR))"
            
        return f"CAST({col1} AS VARCHAR) = CAST({col2} AS VARCHAR)"

    def compare(self, conn_str: str, query1: str, query2: str) -> dict:
        """
        Executes a massive outer join on the remote database using two subqueries.
        Returns the dataframes ready for the Streamlit UI.
        """
        # Create SQLAlchemy Engine
        db_engine = create_engine(conn_str)
        
        # Create lookup for the target architecture
        col_map = {m.file1_column: m.file2_column for m in self.config.column_mappings}
        
        # 1. Build the JOIN condition using mapped target columns
        join_conditions = []
        for pk in self.config.primary_keys:
            mapped_pk = col_map.get(pk, pk)
            join_conditions.append(f"f1.\"{pk}\" = f2.\"{mapped_pk}\"")
        join_clause = " AND ".join(join_conditions)
        
        # 2. Build Validation Checks
        select_cols = [f"COALESCE(f1.\"{pk}\", f2.\"{col_map.get(pk, pk)}\") AS \"{pk}\"" for pk in self.config.primary_keys]
        
        for mapping in self.config.column_mappings:
            c1 = mapping.file1_column
            c2 = mapping.file2_column
            
            select_cols.append(f"f1.\"{c1}\" AS \"File1_{c1}\"")
            select_cols.append(f"f2.\"{c2}\" AS \"File2_{c2}\"")
            
            rule = mapping.validation_rule or self.rules_dict.get(c1)
                
            if rule:
                sql_condition = self._translate_rule_to_sql(c1, c2, rule)
                select_cols.append(f"CASE WHEN {sql_condition} THEN 1 ELSE 0 END AS \"{c1}_IsValid\"")
            else:
                select_cols.append(f"CASE WHEN CAST(f1.\"{c1}\" AS VARCHAR) = CAST(f2.\"{c2}\" AS VARCHAR) THEN 1 ELSE 0 END AS \"{c1}_IsValid\"")
        
        select_clause = ",\n    ".join(select_cols)
        
        # --- EXECUTE MASSIVE PUSHDOWN QUERY ---
        # The FULL OUTER JOIN guarantees we catch all exceptions
        massive_query = f"""
        SELECT 
            {select_clause}
        FROM ({query1}) AS f1
        FULL OUTER JOIN ({query2}) AS f2 
        ON {join_clause}
        """
        
        # We process the results through Pandas since Streamlit handles dataframes well,
        # but the database did 100% of the heavy lifting.
        with db_engine.connect() as conn:
            merged_df = pd.read_sql(text(massive_query), conn)
            
            try:
                count1 = pd.read_sql(text(f"SELECT COUNT(*) FROM ({query1}) AS tmp"), conn).iloc[0, 0]
                count2 = pd.read_sql(text(f"SELECT COUNT(*) FROM ({query2}) AS tmp"), conn).iloc[0, 0]
            except Exception:
                count1, count2 = 0, 0

        # --- SLICE EXCEPTIONS ---
        results = {
            "Total Rows File 1": count1,
            "Total Rows File 2": count2,
            "Missing in File 1 (Found in 2)": pd.DataFrame(),
            "Missing in File 2 (Found in 1)": pd.DataFrame(),
            "Data Mismatches": pd.DataFrame(),
            "Exact Matches": pd.DataFrame(),
            "Mismatch Breakdown": []
        }
        
        if merged_df.empty: return results
        
        first_pk = self.config.primary_keys[0]
        # Some DBs return lowercase columns, we do a fallback logic
        col_list = merged_df.columns.tolist()
        pk1_matched = next((c for c in col_list if c.lower() == f"file1_{first_pk}".lower()), f"File1_{first_pk}")
        pk2_matched = next((c for c in col_list if c.lower() == f"file2_{first_pk}".lower()), f"File2_{first_pk}")
        
        f1_pk_missing = merged_df[pk1_matched].isna() if pk1_matched in merged_df else pd.Series(False, index=merged_df.index)
        f2_pk_missing = merged_df[pk2_matched].isna() if pk2_matched in merged_df else pd.Series(False, index=merged_df.index)
        
        results["Missing in File 1 (Found in 2)"] = merged_df[f1_pk_missing & ~f2_pk_missing].copy()
        results["Missing in File 2 (Found in 1)"] = merged_df[f2_pk_missing & ~f1_pk_missing].copy()
        
        matched_pk_df = merged_df[~f1_pk_missing & ~f2_pk_missing]
        
        if not matched_pk_df.empty:
            # 1 maps to TRUE, 0 maps to FALSE in SQLAlchemy output
            is_valid_cols = [c for c in col_list if c.lower().endswith("_isvalid")]
            
            # Map 1/0 to True/False for stability
            for c in is_valid_cols:
                matched_pk_df[c] = matched_pk_df[c].astype(bool)
                
            all_valid_mask = matched_pk_df[is_valid_cols].all(axis=1)
            results["Exact Matches"] = matched_pk_df[all_valid_mask].copy()
            
            mismatch_df = matched_pk_df[~all_valid_mask].copy()
            results["Data Mismatches"] = mismatch_df
            
            breakdown = []
            for _, row in mismatch_df.iterrows():
                for m in self.config.column_mappings:
                    c1_col = m.file1_column
                    valid_col = next((c for c in col_list if c.lower() == f"{c1_col}_isvalid".lower()), None)
                    
                    if valid_col and not row[valid_col]:
                        c2_col = m.file2_column
                        f1_val_col = next((c for c in col_list if c.lower() == f"file1_{c1_col}".lower()), f"File1_{c1_col}")
                        f2_val_col = next((c for c in col_list if c.lower() == f"file2_{c2_col}".lower()), f"File2_{c2_col}")
                        
                        pk_display = ", ".join([f"{pk}={row[pk]}" for pk in self.config.primary_keys if pk in row])
                        breakdown.append({
                            "Primary Key": pk_display,
                            "Column": f"{c1_col} -> {c2_col}",
                            "File 1 Value": row[f1_val_col] if f1_val_col in row else None,
                            "File 2 Value": row[f2_val_col] if f2_val_col in row else None,
                            "Validation Rule": m.validation_rule or "",
                            "Remarks": f"Failed Rule: {m.validation_rule}" if m.validation_rule else "Exact Match Failed"
                        })
            
            results["Mismatch Breakdown"] = breakdown
            
        return results
