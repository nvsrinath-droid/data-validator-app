"""One adapter per execution tier, so the UI (and CLI) can drive every engine the same way.

Each pair knows how to list columns, fetch a small sample for the AI / mapping grid,
and run the full comparison with the right engine.
"""
from typing import List, Optional

import pandas as pd

from core.comparator import DataComparator
from core.db import get_engine, redact, sample_query
from core.engines.duckdb_engine import DuckDBEngine
from core.engines.sql_pushdown import DEFAULT_SAMPLE_LIMIT, SQLPushdownEngine
from core.results import ComparisonResult
from core.schemas import ValidationConfig

SIDES = ("source", "target")


class DataPair:
    """Source (system of record) + target to compare."""

    signature: tuple = ()  # identifies the inputs; the UI drops a mapping when this changes

    def sample(self, side: str, n: int = 5) -> pd.DataFrame:
        raise NotImplementedError

    def columns(self, side: str) -> List[str]:
        return [str(c) for c in self.sample(side, 1).columns]

    def run(self, config: ValidationConfig) -> ComparisonResult:
        raise NotImplementedError

    def redact(self, message: str) -> str:
        return message


class ConnectorPair(DataPair):
    """Standard tier: in-memory pandas comparison over file or SQL connectors."""

    def __init__(self, source, target, signature: tuple = ()):
        self.connectors = dict(zip(SIDES, (source, target)))
        self.signature = signature

    def sample(self, side, n=5):
        return self.connectors[side].get_sample_data(n)

    def run(self, config):
        return DataComparator(config).compare(self.connectors["source"].read_data(),
                                              self.connectors["target"].read_data())

    def redact(self, message):
        for conn in self.connectors.values():
            engine = getattr(conn, "engine", None)
            message = redact(message, getattr(engine, "url", None))
        return message


class FilePair(DataPair):
    """Massive Data Files tier: DuckDB streams large CSV / Excel files from disk."""

    def __init__(self, source_path: str, target_path: str):
        self.paths = dict(zip(SIDES, (source_path, target_path)))
        self.signature = (source_path, target_path)

    def sample(self, side, n=5):
        path = self.paths[side]
        if path.lower().endswith((".xls", ".xlsx")):
            return pd.read_excel(path, nrows=n)
        return pd.read_csv(path, nrows=n)

    def run(self, config):
        return DuckDBEngine(config).compare(self.paths["source"], self.paths["target"])


class PushdownPair(DataPair):
    """Enterprise tier: both queries run inside one database; only exceptions come back."""

    def __init__(self, url, source_query: str, target_query: str, sample_limit: Optional[int] = DEFAULT_SAMPLE_LIMIT):
        self.url = url
        self.engine = get_engine(url)
        self.queries = dict(zip(SIDES, (source_query, target_query)))
        self.sample_limit = sample_limit
        self.signature = (repr(url), source_query, target_query)

    def sample(self, side, n=5):
        return sample_query(self.engine, self.queries[side], n)

    def run(self, config):
        return SQLPushdownEngine(config).compare(self.engine, self.queries["source"], self.queries["target"],
                                                 sample_limit=self.sample_limit)

    def redact(self, message):
        return redact(message, self.engine.url)
