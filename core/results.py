"""The single result shape returned by every comparison engine."""
from dataclasses import dataclass, field
from typing import Dict, List

import pandas as pd

MISMATCH_COLUMNS = ["Column", "Source Value", "Target Value", "Rule", "Remarks"]


@dataclass
class ComparisonResult:
    total_source: int = 0
    total_target: int = 0
    matched_rows: int = 0            # key in both sides, every compared column matches
    mismatched_rows: int = 0         # key in both sides, at least one column differs
    missing_in_target_count: int = 0  # key only in source
    missing_in_source_count: int = 0  # key only in target
    duplicate_key_count: int = 0     # distinct keys duplicated on either side (excluded from the join)
    mismatches_by_column: Dict[str, int] = field(default_factory=dict)

    # Row-level detail. SQL pushdown caps these at sample_limit rows each; counts above are always exact.
    missing_in_target: pd.DataFrame = field(default_factory=pd.DataFrame)  # source columns
    missing_in_source: pd.DataFrame = field(default_factory=pd.DataFrame)  # target columns
    mismatches: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=MISMATCH_COLUMNS))
    duplicate_keys: pd.DataFrame = field(default_factory=pd.DataFrame)     # Side, key columns, Count

    warnings: List[str] = field(default_factory=list)
    truncated: bool = False  # True when any detail frame was capped

    @property
    def has_exceptions(self) -> bool:
        return bool(self.mismatched_rows or self.missing_in_target_count
                    or self.missing_in_source_count or self.duplicate_key_count)
