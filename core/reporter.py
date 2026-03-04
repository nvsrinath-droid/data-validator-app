import json
import csv
import os
import pandas as pd
from typing import Dict, Any

class Reporter:
    """Handles outputting the comparison results."""
    
    def __init__(self, output_dir: str = "output"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        
    def generate_json_report(self, results: Dict[str, Any], filename: str = "validation_report.json"):
        """Saves the raw results dictionary to a JSON file."""
        filepath = os.path.join(self.output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=4)
        print(f"JSON Report saved to: {filepath}")
        
    def generate_csv_reports(self, results: Dict[str, Any], prefix: str = "report"):
        """Splits the results into readable CSV files."""
        
        # 1. Mismatches Report
        if results.get("mismatches"):
            mismatches_path = os.path.join(self.output_dir, f"{prefix}_mismatches.csv")
            with open(mismatches_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Primary Key(s)", "Column", "File 1 (Source) Value", "File 2 Value"])
                
                for item in results["mismatches"]:
                    pk_str = str(item["primary_keys"])
                    for diff in item["differences"]:
                        writer.writerow([
                            pk_str,
                            diff["column"],
                            diff["file1_value"],
                            diff["file2_value"]
                        ])
            print(f"Mismatches CSV saved to: {mismatches_path}")

        # 2. Missing in File 1 (Only in File 2)
        if results.get("missing_in_file1"):
            missing_f1_path = os.path.join(self.output_dir, f"{prefix}_only_in_file2.csv")
            df = pd.DataFrame(results["missing_in_file1"])
            df.to_csv(missing_f1_path, index=False)
            print(f"Missing in File 1 CSV saved to: {missing_f1_path}")

        # 3. Missing in File 2 (Only in File 1)
        if results.get("missing_in_file2"):
            missing_f2_path = os.path.join(self.output_dir, f"{prefix}_only_in_file1.csv")
            df = pd.DataFrame(results["missing_in_file2"])
            df.to_csv(missing_f2_path, index=False)
            print(f"Missing in File 2 CSV saved to: {missing_f2_path}")
