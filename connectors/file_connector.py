import pandas as pd
from typing import Optional, Union
import io
from .base import BaseConnector

class FileConnector(BaseConnector):
    """Connector for reading local CSV/Excel files or Streamlit UploadedFiles."""
    
    def __init__(self, file_source: Union[str, any], file_name: str = None):
        """
        Accepts either a string path (CLI) or a Streamlit UploadedFile object.
        """
        self.file_source = file_source
        self.file_name = file_name if file_name else getattr(file_source, 'name', str(file_source))
        
    def _read_data_internal(self, nrows: Optional[int] = None) -> pd.DataFrame:
        """Helper to read data with optional row limits."""
        # Handle string path (CLI mode)
        if isinstance(self.file_source, str):
            if self.file_name.endswith('.csv'):
                return pd.read_csv(self.file_source, nrows=nrows)
            elif self.file_name.endswith(('.xls', '.xlsx')):
                return pd.read_excel(self.file_source, nrows=nrows)
            
        # Handle Streamlit UploadedFile mode
        else:
            # We need to reset the buffer pointer so we can read it multiple times
            self.file_source.seek(0) 
            if self.file_name.endswith('.csv'):
                return pd.read_csv(self.file_source, nrows=nrows)
            elif self.file_name.endswith(('.xls', '.xlsx')):
                return pd.read_excel(self.file_source, nrows=nrows)
                
        raise ValueError(f"Unsupported file format: {self.file_name}")

    def read_data(self) -> pd.DataFrame:
        """Read full data into a pandas DataFrame."""
        return self._read_data_internal()
            
    def get_sample_data(self, num_rows: int = 5) -> pd.DataFrame:
        """Returns a small sample of the data for LLM analysis."""
        return self._read_data_internal(nrows=num_rows)
             
    def get_schema(self) -> dict[str, str]:
        """Returns the schema of the data."""
        df = self.get_sample_data(1) 
        return {col: str(dtype) for col, dtype in df.dtypes.items()}
