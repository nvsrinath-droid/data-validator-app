import argparse
import os
import json
from dotenv import load_dotenv

# Load environment variables (e.g., GEMINI_API_KEY)
load_dotenv()

from connectors.file_connector import FileConnector
from ai.agent import GeminiAgent
from core.schemas import ValidationConfig
from core.comparator import DataComparator
from core.reporter import Reporter

def main():
    parser = argparse.ArgumentParser(description="AI-Powered Data Validation Agent")
    parser.add_argument("file1", help="Path to File 1 (Source of Truth)")
    parser.add_argument("file2", help="Path to File 2 (External File to Compare)")
    parser.add_argument("--config", help="Optional path to an existing config.json file to bypass the LLM step", default=None)
    parser.add_argument("--auto", action="store_true", help="Automatically accept AI suggestions without prompting")
    args = parser.parse_args()

    print(f"Initializing Data Validator on:\n - File 1: {args.file1}\n - File 2: {args.file2}\n")

    # 1. Initialize Connectors
    try:
        conn1 = FileConnector(args.file1)
        conn2 = FileConnector(args.file2)
    except Exception as e:
         print(f"Error loading files: {e}")
         return

    config = None

    # 2. Schema Discovery / Configuration Phase
    if args.config:
        print(f"Loading configuration from {args.config}...")
        with open(args.config, 'r') as f:
            config_data = json.load(f)
            config = ValidationConfig(**config_data)
    else:
        print("Gathering samples for AI analysis...")
        sample1 = conn1.get_sample_data(5).to_csv(index=False)
        sample2 = conn2.get_sample_data(5).to_csv(index=False)
        
        print("Requesting configuration from Gemini...")
        agent = GeminiAgent()
        try:
            config = agent.suggest_configuration(sample1, sample2)
            
            print("\n----- AI Suggested Configuration -----")
            print(config.model_dump_json(indent=2))
            print("--------------------------------------\n")
            
            if not args.auto:
                confirm = input("Accept this configuration? (y/n/edit): ").strip().lower()
                if confirm == 'edit':
                    # Allow user to save it, edit it, and rerun
                    temp_path = "temp_config.json"
                    with open(temp_path, 'w') as f:
                        f.write(config.model_dump_json(indent=2))
                    print(f"\nConfiguration saved to {temp_path}.")
                    print(f"Please edit this file and rerun using: python main.py {args.file1} {args.file2} --config {temp_path}")
                    return
                elif confirm != 'y':
                    print("Aborting.")
                    return
                    
        except Exception as e:
            print(f"Failed to generate configuration from AI: {e}")
            print("Please create a configuration JSON manually and pass it using --config")
            return


    # 3. Execution Phase
    print("\nReading full datasets...")
    df1 = conn1.read_data()
    df2 = conn2.read_data()
    
    print("Running comparison engine...")
    comparator = DataComparator(config)
    results = comparator.compare(df1, df2)
    
    # 4. Reporting Phase
    print("\nGenerating Reports...")
    reporter = Reporter()
    reporter.generate_json_report(results)
    
    # Needs pandas imported in reporter to work properly... let's fix that during testing if it crashes
    import pandas as pd
    reporter.pandas = pd # simple hack for now, or we can just import it in the file
    reporter.generate_csv_reports(results)
    
    # Print Quick Summary
    mismatch_count = len(results.get("mismatches", []))
    missing_f1_count = len(results.get("missing_in_file1", []))
    missing_f2_count = len(results.get("missing_in_file2", []))
    
    print("\n----- Validation Summary -----")
    print(f"Row Values Mismatched:   {mismatch_count}")
    print(f"Rows Missing in File 1:  {missing_f1_count}")
    print(f"Rows Missing in File 2:  {missing_f2_count}")
    if mismatch_count == 0 and missing_f1_count == 0 and missing_f2_count == 0:
        print("\nSUCCESS! Files are matching perfectly based on the configuration.")

if __name__ == "__main__":
    main()
