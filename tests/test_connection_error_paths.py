"""The connection-error messages of the Standard and Enterprise tiers must not print file paths either."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

import ui.pages.pushdown as pushdown_page
import ui.pages.standard as standard_page

ROOT = Path(__file__).resolve().parents[1]
SECRET = "Secret Share"


def open_tier(engine):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.session_state["is_guest"] = True
    at.query_params["auth"] = "guest"
    at.query_params["engine"] = engine
    return at.run()


def leaky(tmp_path):
    db = tmp_path / SECRET / "warehouse.db"
    db.parent.mkdir()
    db.touch()                      # the path box now checks that the file exists before a connection is tried
    return db, OSError(f"unable to open database file {db} (also {tmp_path / SECRET / 'other data.csv'})")


def test_pushdown_connection_failure_names_no_path(tmp_path, monkeypatch):
    db, error = leaky(tmp_path)

    def boom(*args, **kwargs):
        raise error
    monkeypatch.setattr(pushdown_page, "PushdownPair", boom)
    at = open_tier("pushdown")
    at.selectbox(key="db_type_pd").set_value("SQLite (Local)").run()
    at.text_input(key="sqlite_pd").set_value(str(db)).run()
    at.text_area(key="pd_q1").set_value("SELECT 1").run()
    at.text_area(key="pd_q2").set_value("SELECT 1").run()
    assert not at.exception, at.exception
    messages = [e.value for e in at.error]
    assert messages and messages[0].startswith("Database connection failed:"), messages
    assert all(SECRET not in m and "warehouse" not in m and "other data" not in m and str(tmp_path) not in m
               for m in messages), messages
    assert "<file>" in messages[0]


def test_standard_connection_failure_names_no_path(tmp_path, monkeypatch):
    db, error = leaky(tmp_path)

    def boom(*args, **kwargs):
        raise error
    monkeypatch.setattr(standard_page, "SQLConnector", boom)
    at = open_tier("standard")
    for radio in at.radio:
        radio.set_value("SQL Database")
    at.run()
    for side in ("src1", "src2"):
        at.selectbox(key=f"db_type_{side}_0").set_value("SQLite (Local)")
    at.run()
    for side in ("src1", "src2"):
        at.text_input(key=f"sqlite_{side}_0").set_value(str(db))
        at.text_area(key=f"q_{side}_0").set_value("SELECT 1")
    at.run()
    assert not at.exception, at.exception
    messages = [e.value for e in at.error]
    assert messages and messages[0].startswith("Error connecting to data source:"), messages
    assert all(SECRET not in m and "warehouse" not in m and "other data" not in m and str(tmp_path) not in m
               for m in messages), messages
    assert "<file>" in messages[0]
