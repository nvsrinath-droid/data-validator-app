import pandas as pd

# File 1: Source of Truth
data1 = {
    'EmpID': [1, 2, 3, 4, 5],
    'Name': ['Alice', 'Bob', 'Charlie', 'David', 'Eve'],
    'Department': ['HR', 'Engineering', 'Engineering', 'Sales', 'Marketing'],
    'Salary': [60000, 90000, 85000, 75000, 65000]
}
df1 = pd.DataFrame(data1)
df1.to_csv('source.csv', index=False)

# File 2: External System (with discrepancies)
data2 = {
    'Employee Identifier': [1, 2, 3, 5, 6], # Missing 4, Extra 6
    'Full Name': ['Alice', 'Robert', 'Charlie', 'Eve', 'Frank'], # Bob is Robert
    'Dept': ['HR', 'Engineering', 'Engineering', 'Marketing', 'Sales'],
    'Annual Salary': [60000, 90000, 90000, 65000, 50000] # Charlie salary mismatch
}
df2 = pd.DataFrame(data2)
df2.to_csv('external.csv', index=False)

print("Created test CSVs: source.csv and external.csv")
