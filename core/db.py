"""Database connection helpers.

URLs are built with SQLAlchemy's URL.create(), so passwords containing @ : / % # etc.
work without manual escaping, and the password is masked whenever the URL is printed.
"""
from typing import List, Optional

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine

DB_TYPES = ["Snowflake", "Microsoft SQL Server", "Oracle", "PostgreSQL", "SQLite (Local)"]
DEFAULT_PORTS = {"Snowflake": "443", "Microsoft SQL Server": "1433", "Oracle": "1521", "PostgreSQL": "5432"}
MSSQL_DRIVERS = ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"]  # preferred first


def installed_mssql_drivers() -> List[str]:
    """SQL Server ODBC drivers installed on this machine (empty if pyodbc/unixODBC is unavailable)."""
    try:
        import pyodbc
        return [d for d in pyodbc.drivers() if "SQL Server" in d]
    except Exception:  # ImportError, or OSError when the ODBC manager library is missing
        return []


def default_mssql_driver() -> str:
    """Driver 18 if installed, else 17 if installed, else 18."""
    installed = installed_mssql_drivers()
    return next((d for d in MSSQL_DRIVERS if d in installed), MSSQL_DRIVERS[0])


def build_url(db_type: str, host: str = "", port: str = "", database: str = "",
              user: str = "", password: str = "", sqlite_path: str = "",
              mssql_driver: Optional[str] = None, trust_server_certificate: bool = False) -> URL:
    """SQL Server only: mssql_driver defaults to default_mssql_driver(). Driver 18 encrypts by
    default (Encrypt=yes); set trust_server_certificate for servers with a self-signed certificate."""
    if db_type == "SQLite (Local)":
        return URL.create("sqlite", database=sqlite_path)

    port_num = int(port) if str(port).strip() else None
    if db_type == "Snowflake":
        # snowflake-sqlalchemy wants the account identifier, not the full hostname;
        # database may be "DB" or "DB/SCHEMA".
        account = host.strip().removeprefix("https://").split(".snowflakecomputing.com")[0]
        return URL.create("snowflake", username=user, password=password, host=account, database=database)
    if db_type == "Microsoft SQL Server":
        query = {"driver": mssql_driver or default_mssql_driver()}
        if trust_server_certificate:
            query["TrustServerCertificate"] = "yes"
        return URL.create("mssql+pyodbc", username=user, password=password, host=host, port=port_num,
                          database=database, query=query)
    if db_type == "Oracle":
        return URL.create("oracle+oracledb", username=user, password=password, host=host, port=port_num,
                          query={"service_name": database})
    if db_type == "PostgreSQL":
        return URL.create("postgresql+psycopg2", username=user, password=password, host=host, port=port_num,
                          database=database)
    raise ValueError(f"Unsupported database type: {db_type}")


def redact(message: str, url: Optional[URL]) -> str:
    """Remove the password from an error message before showing it to the user."""
    if url is not None and url.password:
        message = message.replace(str(url.password), "***")
    return message


def get_engine(url) -> Engine:
    return url if isinstance(url, Engine) else create_engine(url)


def sample_query(url, query: str, n: int = 5) -> pd.DataFrame:
    """First n rows of a query, using the right row-limit syntax for the dialect."""
    from core.engines.sql_builder import clean_query, dialect_for

    engine = get_engine(url)
    sql = dialect_for(engine.dialect.name).limit(clean_query(query), n)
    with engine.connect() as conn:
        res = conn.exec_driver_sql(sql)
        return pd.DataFrame(res.fetchall(), columns=list(res.keys()))
