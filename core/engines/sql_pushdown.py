from typing import Optional, Union

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine

from core.normalize import INFERENCE_SAMPLE
from core.results import ComparisonResult
from core.schemas import ValidationConfig

from .sql_builder import SQLComparison, clean_query, dialect_for, plan_from_samples

DEFAULT_SAMPLE_LIMIT = 1000


class SQLPushdownEngine:
    """
    Executes data validation inside a remote database (Snowflake, Oracle, SQL Server,
    Postgres, SQLite). Normalization, the join and all counting run as SQL; only
    aggregate counts and a capped sample of exceptions are downloaded.
    """

    def __init__(self, config: ValidationConfig):
        self.config = config

    def compare(self, db: Union[str, URL, Engine], query1: str, query2: str,
                sample_limit: Optional[int] = DEFAULT_SAMPLE_LIMIT) -> ComparisonResult:
        engine = db if isinstance(db, Engine) else create_engine(db)
        dialect = dialect_for(engine.dialect.name, engine.dialect.identifier_preparer.quote)
        q1, q2 = clean_query(query1), clean_query(query2)
        src_rel, tgt_rel = f"({q1})", f"({q2})"

        with engine.connect() as conn:
            def run(sql: str):
                # exec_driver_sql: no bind-parameter parsing, so ':' in user SQL is safe
                res = conn.exec_driver_sql(sql)
                return list(res.keys()), [tuple(r) for r in res.fetchall()]

            c1, r1 = run(dialect.limit(q1, INFERENCE_SAMPLE))
            c2, r2 = run(dialect.limit(q2, INFERENCE_SAMPLE))
            plan = plan_from_samples(self.config, c1, r1, c2, r2)
            return SQLComparison(plan, dialect, src_rel, tgt_rel).run(run, sample_limit)
