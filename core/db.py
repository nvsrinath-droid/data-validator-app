"""Database connection helpers.

URLs are built with SQLAlchemy's URL.create(), so passwords containing @ : / % # etc.
work without manual escaping, and the password is masked whenever the URL is printed.
"""
import re
from typing import Iterable, List, Optional

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


def sqlite_file_of(url) -> List[str]:
    """The database file of a SQLite URL as a one-item list (empty for any other database), ready to pass to
    scrub_paths as a known path."""
    if isinstance(url, URL) and url.get_backend_name() == "sqlite" and url.database:
        return [url.database]
    return []


def redact(message: str, url: Optional[URL]) -> str:
    """Remove the password from an error message before showing it to the user."""
    if url is not None and url.password:
        message = message.replace(str(url.password), "***")
    return message


_SEP = r"[\\/]+"        # / and \ alike, and any run of them: Python repr() doubles every backslash in an error
# A path we did not get told about is only recognised when it is quoted (as OSError, DuckDB and pandas quote file
# names) and starts like a Windows path: a drive letter ("C:\" or "C:/") or "\\" (UNC, or its repr() form).
_QUOTED_WINDOWS_PATH = re.compile(
    r"""(?P<q>['"])(?:[A-Za-z]:[\\/]|\\\\)(?:(?!(?P=q))[^\r\n])*(?P=q)""")


def _known_path_pattern(path: str) -> Optional[str]:
    """A regex for one known path that matches it in every separator spelling (/, \\, doubled, mixed)."""
    parts = [p for p in re.split(_SEP, path)]
    if not any(parts):
        return None                                   # "/" or "\\" alone would match every slash in the message
    return _SEP.join(re.escape(p) for p in parts)


def scrub_paths(message: str, known: Iterable[str] = ()) -> str:
    r"""Replace file-system paths in an error message with <file> before showing it to the user: the text of a
    pandas / DuckDB / OS error can name the server's folders (the private upload folder, the temp directory, the
    file the user typed).
    - `known` paths (the typed path, the upload paths) are replaced wherever they appear, ignoring case and with
      any separator spelling, so spaces and a missing extension do not matter.
    - Any other path is replaced only when it is quoted and starts with a drive letter or \\. Everything else is
      left alone, so "Debit / Credit", "N / A", "CORP\jdoe", URLs and dates survive. A path that is neither known
      nor quoted in that way is not recognised: pass it in `known`."""
    patterns = sorted({pat for p in known if p and (pat := _known_path_pattern(str(p)))}, key=len, reverse=True)
    if patterns:
        message = re.sub("|".join(patterns), "<file>", message, flags=re.IGNORECASE)
    return _QUOTED_WINDOWS_PATH.sub(lambda m: m.group("q") + "<file>" + m.group("q"), message)


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
