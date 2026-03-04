import pandas as pd
import random

def generate_datasets():
    random.seed(99)
    
    # Generate 10 products
    f1_data = []
    
    categories = ['Electronics', 'Clothing', 'Home']
    
    for i in range(1, 11):
        f1_data.append({
            'ProductID': f'PRD-{i:03d}',
            'ProductName': f'Item Model {i}',
            'Category': random.choice(categories),
            'CostPrice': random.randint(10, 500) * 1.0,
            'Status': 'ACTIVE'
        })
        
    df1 = pd.DataFrame(f1_data)
    
    f2_data = []
    for row in f1_data:
        prod_id = row['ProductID']
        
        # Exact match
        name = row['ProductName']
        status = row['Status']
        cost = row['CostPrice']
        
        # Introduce variances to test AI Rules
        
        if prod_id == 'PRD-002':
            # Case sensitivity discrepancy
            status = 'active' 
            name = 'ITEM MODEL 2'
            
        elif prod_id == 'PRD-004':
            # Minor dollar variance (+ $0.50)
            cost = cost + 0.50
            
        elif prod_id == 'PRD-007':
            # 2% variance
            cost = cost * 1.02
            
        elif prod_id == 'PRD-009':
            # Massive variance (should be flagged even with a 5% rule)
            cost = cost * 1.50
            
        f2_data.append({
            'ID': prod_id,
            'Product_Desc': name,
            'Cat': row['Category'],
            'Unit_Cost': cost,
            'ProductStatus': status
        })
        
    df2 = pd.DataFrame(f2_data)

    df1.to_csv('inventory_system.csv', index=False)
    df2.to_csv('vendor_catalog.csv', index=False)
    
    print("Files created: inventory_system.csv and vendor_catalog.csv")

if __name__ == "__main__":
    generate_datasets()
