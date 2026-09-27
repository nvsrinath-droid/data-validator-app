from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from .rules import RuleSpec

CompareAs = Literal["auto", "numeric", "string", "date"]


class ColumnMap(BaseModel):
    file1_column: str
    file2_column: str
    validation_rule: Optional[str] = None
    # Structured form of validation_rule. When None, engines parse validation_rule
    # deterministically; the AI agent can fill this in for rules the parser can't read.
    rule_spec: Optional[RuleSpec] = None
    # Force a comparison type instead of inferring it from the data.
    compare_as: CompareAs = "auto"


class ValidationConfig(BaseModel):
    """Schema for the validation configuration."""
    primary_keys: List[str] = Field(..., description="List of column names used to uniquely identify and join rows between File 1 and File 2.")
    column_mappings: List[ColumnMap] = Field(..., description="List of mappings from File 1 columns to File 2 columns.")
    ignore_columns: Optional[List[str]] = Field(default_factory=list, description="List of columns from File 1 to ignore during the comparison.")
    # Trim leading/trailing whitespace on string values (JD Edwards pads CHAR fields).
    trim_strings: bool = True
    # Treat empty strings as NULL (Oracle does this natively; JDE uses blanks for "no value").
    blank_as_null: bool = True
