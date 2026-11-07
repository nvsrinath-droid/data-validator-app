"""scrub_paths: no part of a file path may survive in an error message, and ordinary text must."""
import os

import pytest

from core.db import scrub_paths

WIN = r"C:\Users\Ven Nanduri\My Data\sales.csv"
WIN_FWD = "C:/Users/Ven Nanduri/My Data/sales.csv"
UNC = r"\\fileserver\finance share\My Data\sales.csv"
UNC_FWD = "//fileserver/finance share/My Data/sales.csv"
RELATIVE = [r"..\My Data\sales.csv", "./My Data/sales.csv", "samples/inventory_system.csv", r"data\2024\sales.csv"]
# every piece of every path above; none may remain after scrubbing
PIECES = ["Users", "Ven", "Nanduri", "My Data", "My", "Data", "sales", "fileserver", "finance", "inventory_system",
          "samples", "2024"]


def assert_no_path_left(text, pieces=PIECES):
    for piece in pieces:
        assert piece not in text, (piece, text)
    assert "<file>" in text, text


def real_os_error(path):
    """The genuine message Python produces when a file cannot be opened."""
    with pytest.raises(OSError) as err:
        open(path)
    return str(err.value)


@pytest.mark.skipif(os.name != "nt", reason="the Windows-style path is only a missing file name on Windows")
def test_a_real_oserror_for_a_missing_file_with_spaces_keeps_no_part_of_the_path():
    message = real_os_error(WIN)
    assert "Nanduri" in message and "\\\\" in message                  # the doubled-backslash repr form
    assert_no_path_left(scrub_paths(message))                           # by pattern alone
    assert_no_path_left(scrub_paths(message, [WIN]))                    # and when the path is known


def test_a_real_oserror_for_a_missing_file_in_a_tmp_folder_with_spaces(tmp_path):
    path = tmp_path / "Secret Folder" / "sales data.csv"
    message = real_os_error(str(path))
    for known in ([], [str(path)]):
        out = scrub_paths(message, known)
        assert "Secret" not in out and "sales" not in out and tmp_path.name not in out, out


@pytest.mark.parametrize("path", [WIN, WIN_FWD, UNC, UNC_FWD, *RELATIVE])
@pytest.mark.parametrize("template", [
    "{p}",
    "[Errno 2] No such file or directory: '{p}'",
    "IO Error: Could not open file \"{p}\" for reading (line 4); try again later",
    "Failed to read {p} because the header is missing. Check the delimiter.",
])
def test_every_path_form_is_removed_from_a_longer_message(path, template):
    for spelled in (path, path.replace("\\", "\\\\")):                  # as typed, and as repr() shows it
        out = scrub_paths(template.format(p=spelled))
        assert_no_path_left(out)
        for tail in ("(line 4); try again later", "Check the delimiter.", "header is missing"):
            if tail in template:
                assert tail in out                                     # the useful part of the message stays


def test_two_paths_in_one_message_and_text_between_them_survives():
    out = scrub_paths(rf"cannot compare {WIN} with {UNC} because the keys differ")
    assert_no_path_left(out)
    assert out == "cannot compare <file> with <file> because the keys differ"


@pytest.mark.parametrize("text", [
    r"Login failed for user 'CORP\jdoe'.",
    "Could not convert '2024/01/15' with format /%Y/%m/",
    r"Invalid escape '\N' in column; sniffed delimiter '\t'",
    "Use either and/or; N/A; 3/4 is fine; ratio 10/20",
    "https://example.com/files/report.html was slow",
    "Column 'a.b' not found. Available: ['x', 'y']",
])
def test_things_that_are_not_paths_are_left_alone(text):
    assert scrub_paths(text) == text


LOGIN_MESSAGES = [
    r"Login failed for user 'CORP\jdoe'.",
    "Login failed for user 'CORP\\\\jdoe'.",                   # the doubled form repr() gives
    r"('28000', '[28000] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]Login failed for user 'CORP\svc_etl'.')",
    r"ORA-01017: invalid username/password; logon denied for DOMAIN\ven",
]


@pytest.mark.parametrize("message", LOGIN_MESSAGES)
def test_a_domain_login_is_not_a_path_in_any_pair(message, tmp_path):
    """The backslash in DOMAIN\\user is not a path: the message is the only clue the user has."""
    from sqlalchemy.engine import URL
    from core.sources import ConnectorPair, FilePair, PushdownPair

    class Conn:
        engine = type("E", (), {"url": URL.create("mssql+pyodbc", username="u", password="pw", host="h")})()

    pushdown = PushdownPair.__new__(PushdownPair)                  # no database needed to test redact()
    pushdown.engine = Conn.engine
    pairs = [ConnectorPair(Conn(), Conn()), FilePair(str(tmp_path / "a.csv"), str(tmp_path / "b.csv")), pushdown]
    assert scrub_paths(message) == message
    for pair in pairs:
        assert pair.redact(message) == message


def test_known_paths_with_spaces_are_replaced_in_every_spelling(tmp_path):
    known = str(tmp_path / "My Upload Dir" / "q_1.csv")
    for spelling in (known, known.replace("\\", "/"), known.replace("\\", "\\\\")):
        assert scrub_paths(f"bad file {spelling}!", [known]) == "bad file <file>!"
