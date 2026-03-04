import pandas as pd
from sqlalchemy import create_engine, text
from typing import Optional
from .base import BaseConnector

class SQLConnector(BaseConnector):
    """
    Connector for reading directly from a SQL Database.
    Supports any database SQLAlchemy supports (Postgres, MySQL, SQLite, Snowflake, etc).
    """
    
    def __init__(self, connection_string: str, query: str):
        """
        Initializes the connector with database credentials and the query to execute.
        
        Args:
            connection_string: e.g. 'sqlite:///my_local_db.db' or 'postgresql://user:pass@localhost/db'
            query: The SQL query to extract the data for validation. e.g. 'SELECT * FROM users'
        """
        self.connection_string = connection_string
        self.query = query
        self.engine = create_engine(self.connection_string)
        
    def _read_data_internal(self, nrows: Optional[int] = None) -> pd.DataFrame:
        """Helper to execute the query and return a DataFrame, optionally limited."""
        query_to_run = self.query
        
        # If we only need a sample, we modify the query to add a LIMIT clause
        # Note: This is a simplistic limit injection. For production, you might 
        # want to use SQLAlchemy's select().limit() or wrap it in a CTE.
        if nrows is not None:
             # Basic injection for standard SQL and SQLite. 
             # (SQL Server uses TOP, Oracle uses ROWNUM, so this needs dialect awareness in production)
             if "limit" not in query_to_run.lower():
                 query_to_run = f"{query_to_run} LIMIT {nrows}"
                 
        with self.engine.connect() as conn:
            return pd.read_sql(text(query_to_run), conn)

    def read_data(self) -> pd.DataFrame:
        """Reads the full dataset returned by the query."""
        return self._read_data_internal()
            
    def get_sample_data(self, num_rows: int = 5) -> pd.DataFrame:
        """Retrieves a small subset of records for the AI to analyze the schema."""
        return self._read_data_internal(nrows=num_rows)
             
    def get_schema(self) -> dict[str, str]:
        """Returns the dictionary mapping of columns to their data types."""
        df = self.get_sample_data(1) 
        return {col: str(dtype) for col, dtype in df.dtypes.items()}
