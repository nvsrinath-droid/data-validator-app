"""Mapping grid <-> ValidationConfig, and saved mapping templates (Excel/CSV)."""
import io
from typing import List, Sequence

import pandas as pd

from .rules import rule_preview
from .schemas import ColumnMap, ValidationConfig

SOURCE_COL, TARGET_COL, RULE_COL, PK_COL = "File 1 Column", "File 2 Column", "Validation Rule (Optional)", "Is Primary Key"
GRID_COLUMNS = [SOURCE_COL, TARGET_COL, RULE_COL]
PREVIEW_COL = "Interpreted As"  # read-only, shown next to the rule in the mapping grid


def _cell(value) -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() in ("none", "nan") else text


def config_to_grid(config: ValidationConfig) -> pd.DataFrame:
    rows = [{SOURCE_COL: m.file1_column, TARGET_COL: m.file2_column, RULE_COL: m.validation_rule or ""}
            for m in config.column_mappings]
    return pd.DataFrame(rows, columns=GRID_COLUMNS)


def with_rule_preview(grid: pd.DataFrame) -> pd.DataFrame:
    """The editable grid columns plus a read-only preview of how each rule will be applied."""
    out = grid[GRID_COLUMNS].reset_index(drop=True)
    out[PREVIEW_COL] = [rule_preview(_cell(v)) for v in out[RULE_COL]]
    return out


def preview_is_stale(grid: pd.DataFrame) -> bool:
    """True when a rule was edited and the preview column no longer describes it."""
    return list(with_rule_preview(grid)[PREVIEW_COL]) != [_cell(v) for v in grid[PREVIEW_COL]]


def config_from_grid(grid: pd.DataFrame, primary_keys: Sequence[str], **options) -> ValidationConfig:
    """Build a config from the edited grid, dropping rows without both columns."""
    mappings = []
    for _, row in grid.iterrows():
        src, tgt, rule = _cell(row.get(SOURCE_COL)), _cell(row.get(TARGET_COL)), _cell(row.get(RULE_COL))
        if src and tgt:
            mappings.append(ColumnMap(file1_column=src, file2_column=tgt, validation_rule=rule or None))
    return ValidationConfig(primary_keys=list(primary_keys), column_mappings=mappings, **options)


def manual_config(source_columns: Sequence[str], target_columns: Sequence[str]) -> ValidationConfig:
    """Starter grid: every source column, paired with the same-named target column if one exists."""
    by_name = {str(c).strip().lower(): str(c) for c in target_columns}
    mappings = [ColumnMap(file1_column=str(c), file2_column=by_name.get(str(c).strip().lower(), ""))
                for c in source_columns]
    return ValidationConfig(primary_keys=[], column_mappings=mappings)


def read_template(file) -> ValidationConfig:
    """Load a saved template (uploaded file or path). Raises ValueError if the format is wrong."""
    name = getattr(file, "name", str(file))
    frame = pd.read_excel(file) if name.lower().endswith((".xls", ".xlsx")) else pd.read_csv(file)
    missing = [c for c in GRID_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"Invalid template: missing column(s) {missing}. Expected {GRID_COLUMNS + [PK_COL]}.")
    keys: List[str] = []
    if PK_COL in frame.columns:
        flags = frame[PK_COL].map(lambda v: _cell(v).lower() in ("true", "1", "yes", "y", "t"))
        keys = [_cell(v) for v in frame.loc[flags, SOURCE_COL] if _cell(v)]
    return config_from_grid(frame, keys)


def template_bytes(grid: pd.DataFrame, primary_keys: Sequence[str]) -> bytes:
    frame = grid[GRID_COLUMNS].copy()
    frame[PK_COL] = frame[SOURCE_COL].isin(primary_keys)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Mappings")
    return buffer.getvalue()
