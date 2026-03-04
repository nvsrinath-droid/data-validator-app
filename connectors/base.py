from abc import ABC, abstractmethod
import pandas as pd
from typing import Mapping, Any, Optional

class BaseConnector(ABC):
    """Abstract base class for data connectors."""
    
    @abstractmethod
    def read_data(self) -> pd.DataFrame:
        """Read data into a pandas DataFrame."""
        pass
    
    @abstractmethod
    def get_sample_data(self, num_rows: int = 5) -> pd.DataFrame:
        """Returns a small sample of the data for LLM analysis."""
        pass

    @abstractmethod
    def get_schema(self) -> dict[str, str]:
        """Returns the schema of the data."""
        pass
