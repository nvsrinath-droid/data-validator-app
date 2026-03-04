import pandas as pd
import random
from datetime import datetime, timedelta

def generate_datasets():
    # Set seed for reproducibility
    random.seed(42)
    
    # ---------------------------------------------------------
    # FILE 1: Source System (HR Database)
    # The clean source of truth, but contains some internal columns
    # we don't care about comparing.
    # ---------------------------------------------------------
    
    # Generate 25 employees (IDs 1001 to 1025)
    f1_data = []
    departments = ['Engineering', 'Sales', 'Marketing', 'HR', 'Finance']
    
    for i in range(1001, 1026):
        f1_data.append({
            'EmployeeID': i,
            'FirstName': f'First_{i}',
            'LastName': f'Last_{i}',
            'Department': random.choice(departments),
            'BaseSalary': random.randint(60000, 150000),
            'HireDate': (datetime(2020, 1, 1) + timedelta(days=random.randint(0, 1000))).strftime('%Y-%m-%d'),
            # Internal columns not present in File 2
            'InternalSystemID': f'SYS-{i}',
            'DeskLocation': f'Bldg-{random.randint(1,4)}-Seat-{random.randint(100,999)}'
        })
        
    df1 = pd.DataFrame(f1_data)
    
    
    # ---------------------------------------------------------
    # FILE 2: External System (Payroll Provider)
    # Has a different structure:
    # - Names are combined
    # - Department is abbreviated
    # - Salary is named Annual Pay
    # - Contains unique columns we don't care about
    # - MISSING rows (Employee 1005 and 1012)
    # - EXTRA rows (Employee 1026 and 1027)
    # - MISMATCHED data (Salary for 1003 and 1020)
    # ---------------------------------------------------------
    
    f2_data = []
    
    dept_map = {
        'Engineering': 'ENG',
        'Sales': 'SLS',
        'Marketing': 'MKT',
        'HR': 'HR',
        'Finance': 'FIN'
    }
    
    for row in f1_data:
        emp_id = row['EmployeeID']
        
        # Scenario 1: Missing Rows 
        # Skip 1005 and 1012 so they only exist in File 1
        if emp_id in (1005, 1012):
            continue
            
        salary = row['BaseSalary']
        
        # Scenario 2: Mismatched Values
        # Payroll system has the wrong salary for 1003 and 1020
        if emp_id == 1003:
            salary = salary - 5000
        elif emp_id == 1020:
             salary = salary + 2500
            
        f2_data.append({
            'Emp_Num': emp_id,
            'Full_Name': f"{row['FirstName']} {row['LastName']}", 
            'Dept_Code': dept_map[row['Department']],
            'Annual_Pay': salary,
            # Payroll specific column not in source
            'TaxBracket': f'TB-{random.randint(1,5)}',
            'DirectDeposit': random.choice([True, False])
        })
        
    # Scenario 3: Extra Rows
    # Add fake employees that only exist in the Payroll system
    f2_data.append({
        'Emp_Num': 1026,
        'Full_Name': 'Ghost Employee1',
        'Dept_Code': 'ENG',
        'Annual_Pay': 75000,
        'TaxBracket': 'TB-3',
        'DirectDeposit': True
    })
    
    f2_data.append({
        'Emp_Num': 1027,
        'Full_Name': 'Ghost Employee2',
        'Dept_Code': 'SLS',
        'Annual_Pay': 85000,
        'TaxBracket': 'TB-2',
        'DirectDeposit': False
    })

    df2 = pd.DataFrame(f2_data)

    # Save to CSV
    df1.to_csv('hr_source_data.csv', index=False)
    df2.to_csv('payroll_external_data.csv', index=False)
    
    print(f"Generated File 1 (Source): hr_source_data.csv ({len(df1)} rows, {len(df1.columns)} columns)")
    print(f"Generated File 2 (External): payroll_external_data.csv ({len(df2)} rows, {len(df2.columns)} columns)")
    print("Files created successfully.")

if __name__ == "__main__":
    generate_datasets()
