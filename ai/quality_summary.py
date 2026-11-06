"""The only code that turns quality data into LLM prompt input.

Prompts are built from *summaries*, never from rows:
  - a profile summary: column names, inferred kinds, null %, distinct counts, row count
  - a result summary: check parameters, status, measured metric and violation count
Not sent, ever: sample rows, offending values, result messages and error messages (they can quote data, for
example the newest date), database type names (an ENUM type spells out its values), and file paths.

Sent only when the caller opts in for that run (include_extremes): per-column min/max, and the freshness
metric (an age in hours, which with "now" reveals the newest timestamp).

What IS sent: column names and reference-table names, because without them the model cannot name a check.
Names can be sensitive, and a file without a header row turns its first data row into "column names". So:
  - names that look like data (numbers, dates, empty, very long) are replaced with placeholders col_1...col_n,
    and if half or more of a table's names look like data the whole header row is treated as data and every
    name is replaced (a header row of plain text such as ACME-SECRET cannot be told from real names otherwise);
  - hide_names=True replaces every column name, for tables whose names are themselves sensitive.
Placeholders are mapped back to the real names locally (ColumnAliases.restore); the model never sees the mapping.
"""
from typing import Any, Dict, Iterable, List, Optional

from core.normalize import ISO_DATE_RE, NUMERIC_RE
from core.quality.profile import TableProfile
from core.quality.specs import QualityResult

MAX_COLUMNS = 200
MAX_PLAIN_NAME = 64


def looks_like_data(name: str) -> bool:
    """True for a "column name" that is evidently a cell value: a number, a date, empty, or a long sentence."""
    text = str(name).strip()
    return (not text or len(text) > MAX_PLAIN_NAME or bool(NUMERIC_RE.match(text)) or bool(ISO_DATE_RE.match(text)))


class ColumnAliases:
    """Real column name <-> the placeholder sent to the LLM (or the name itself when it is safe to send)."""

    def __init__(self, names: Iterable[str], hide_all: bool = False, prefix: str = "col"):
        names = list(names)
        flagged = [looks_like_data(n) for n in names]
        # Half or more of the names are data: the header row is probably a data row, so none of it is trusted.
        replace_all = hide_all or (bool(names) and 2 * sum(flagged) >= len(names))
        keep = {n for n, f in zip(names, flagged) if not (replace_all or f)}
        self.to_alias: Dict[str, str] = {}
        self.from_alias: Dict[str, str] = {}
        for i, (name, flag) in enumerate(zip(names, flagged), start=1):
            if not (replace_all or flag):
                continue
            alias = f"{prefix}_{i}"
            while alias in keep or alias in self.from_alias:
                alias += "_"
            self.to_alias[name] = alias
            self.from_alias[alias] = name
        self.names = set(names)

    def alias(self, name: str) -> str:
        return self.to_alias.get(name, name)

    def restore(self, name: str) -> Optional[str]:
        """The real column for a name the model used, or None if it is neither a placeholder nor a sent name."""
        if name in self.from_alias:
            return self.from_alias[name]
        if name in self.names and name not in self.to_alias:
            return name
        return None


def profile_summary(profile: TableProfile, include_extremes: bool = False, hide_names: bool = False,
                    aliases: Optional[ColumnAliases] = None) -> Dict[str, Any]:
    aliases = aliases or ColumnAliases([c.name for c in profile.columns], hide_names)
    columns = []
    for c in profile.columns[:MAX_COLUMNS]:
        entry: Dict[str, Any] = {
            "name": aliases.alias(c.name), "kind": c.kind.value,
            "null_pct": round(c.null_pct, 2), "distinct_count": c.distinct_count,
            "unique": c.is_unique, "nonconforming_count": c.nonconforming_count,
        }
        if include_extremes and c.min is not None:
            entry["min"], entry["max"] = c.min, c.max
        columns.append(entry)
    summary: Dict[str, Any] = {"row_count": profile.row_count, "columns": columns}
    if len(profile.columns) > MAX_COLUMNS:
        summary["columns_omitted"] = len(profile.columns) - MAX_COLUMNS
    return summary


def _placeholder(prefix: str, n: int, taken: set) -> str:
    alias = f"{prefix}_{n}"
    while alias in taken:
        alias += "_"
    return alias


def result_summary(result: QualityResult, include_extremes: bool = False, hide_names: bool = False) -> Dict[str, Any]:
    """Structured counts for the LLM. A name is sent only if it is verified to be a real column of the table
    (or of a reference table the run loaded); anything else - a typo, a column from another file, a value pasted
    into a check, or every name when the result carries no column list - is replaced by a placeholder."""
    aliases = ColumnAliases(result.columns, hide_names)
    taken = set(result.columns) | set(aliases.from_alias)
    unknown_cols: Dict[str, str] = {}
    unknown_refs: Dict[str, str] = {}
    ref_cols: Dict[str, str] = {}
    checks: List[Dict[str, Any]] = []
    for r in result.results:
        spec = r.check.model_dump(mode="json", exclude_none=True)
        column = spec["column"]
        spec["column"] = (aliases.alias(column) if column in aliases.names else
                          unknown_cols.setdefault(column, _placeholder("unknown_col", len(unknown_cols) + 1, taken)))
        if "ref_name" in spec:
            ref_name, ref_column = spec["ref_name"], spec["ref_column"]
            known_ref = ref_name in result.ref_columns
            if not known_ref:
                spec["ref_name"] = unknown_refs.setdefault(ref_name, _placeholder("unknown_ref", len(unknown_refs) + 1, taken))
            safe_column = (known_ref and ref_column in result.ref_columns[ref_name] and not hide_names
                           and not looks_like_data(ref_column))
            if not safe_column:
                spec["ref_column"] = ref_cols.setdefault(ref_column, _placeholder("ref_col", len(ref_cols) + 1, taken))
        metric = None if r.metric is None else round(r.metric, 4)
        if r.check.type == "freshness" and not include_extremes:
            metric = None  # the age, plus "now", is the newest timestamp in the data
        checks.append({"check": spec, "status": r.status, "metric": metric, "violations": r.violations})
    return {"row_count": result.row_count, "checks": checks}
