import pandas as pd
from core.schemas import ValidationConfig, ColumnMap
from core.engines.duckdb_engine import DuckDBEngine

print("Creating dummy files...")
df1 = pd.DataFrame({"ID": [1, 2], "Name": ["Alice", "Bob"], "Price": [10.50, 20.00]})
df2 = pd.DataFrame({"ID": [1, 2], "Name": ["Alice", "Bo b"], "Price": [10.50, 20.00]})

df1.to_csv("d1.csv", index=False)
df2.to_csv("d2.csv", index=False)

conf = ValidationConfig(
    primary_keys=["ID"],
    column_mappings=[
        ColumnMap(file1_column="Name", file2_column="Name", validation_rule="ignore spaces")
    ]
)

print("Running DuckDB Engine...")
engine = DuckDBEngine(conf)
res = engine.compare("d1.csv", "d2.csv")

print(res["Data Mismatches"])
print("Success!")
