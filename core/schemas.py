from pydantic import BaseModel, Field
from typing import Dict, List, Optional

class ColumnMap(BaseModel):
    file1_column: str
    file2_column: str
    validation_rule: Optional[str] = None

class ValidationConfig(BaseModel):
    """Schema for the validation configuration."""
    primary_keys: List[str] = Field(..., description="List of column names used to uniquely identify and join rows between File 1 and File 2.")
    column_mappings: List[ColumnMap] = Field(..., description="List of mappings from File 1 columns to File 2 columns.")
    ignore_columns: Optional[List[str]] = Field(default_factory=list, description="List of columns from File 1 to ignore during the comparison.")
