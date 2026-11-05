from typing import Union

import pandas as pd
from sqlalchemy.engine import URL, Engine

from core.db import get_engine, sample_query
from .base import BaseConnector


class SQLConnector(BaseConnector):
    """
    Connector for reading directly from a SQL Database.
    Supports any database SQLAlchemy supports (Postgres, SQL Server, Oracle, SQLite, Snowflake, etc).
    """

    def __init__(self, connection: Union[str, URL, Engine], query: str):
        """
        Args:
            connection: a SQLAlchemy URL (see core.db.build_url), URL string or Engine
            query: The SQL query to extract the data for validation. e.g. 'SELECT * FROM users'
        """
        self.query = query
        self.engine = get_engine(connection)

    def read_data(self) -> pd.DataFrame:
        """Reads the full dataset returned by the query."""
        with self.engine.connect() as conn:
            res = conn.exec_driver_sql(self.query.strip().rstrip(";"))
            return pd.DataFrame(res.fetchall(), columns=list(res.keys()))

    def get_sample_data(self, num_rows: int = 5) -> pd.DataFrame:
        """Retrieves a small subset of records (dialect-aware LIMIT / TOP / FETCH FIRST)."""
        return sample_query(self.engine, self.query, num_rows)

    def get_schema(self) -> dict[str, str]:
        """Returns the dictionary mapping of columns to their data types."""
        df = self.get_sample_data(1)
        return {col: str(dtype) for col, dtype in df.dtypes.items()}
