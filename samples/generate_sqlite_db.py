import sqlite3
import pandas as pd

def construct_local_db():
    print("Building local SQLite database for testing...")
    
    # Connect (creates file if it doesn't exist)
    conn = sqlite3.connect('local_production.db')
    
    # Create a dummy table representing a production Employees table
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            emp_id TEXT PRIMARY KEY,
            full_name TEXT,
            department TEXT,
            salary REAL,
            status TEXT
        )
    ''')
    
    # Insert some dummy records
    records = [
        ('EMP001', 'Alice Smith', 'Engineering', 120000.00, 'Active'),
        ('EMP002', 'Bob Jones', 'Marketing', 95000.00, 'Active'),
        ('EMP003', 'Charlie Brown', 'Sales', 110000.50, 'On Leave'),
        ('EMP004', 'Diana Prince', 'Engineering', 135000.00, 'Active'),
        ('EMP005', 'Evan Wright', 'HR', 85000.00, 'Terminated')
    ]
    
    cursor.executemany('INSERT OR REPLACE INTO employees VALUES (?, ?, ?, ?, ?)', records)
    conn.commit()
    
    print("Database built successfully: local_production.db")
    print("Table: 'employees'")
    
    # Verify data
    df = pd.read_sql('SELECT * FROM employees', conn)
    print("\nSample Data:")
    print(df.head())
    
    conn.close()

if __name__ == "__main__":
    construct_local_db()
