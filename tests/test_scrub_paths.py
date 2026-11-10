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
    for known in ([str(path)], [str(path).upper()], *([[]] if os.name == "nt" else [])):   # a drive-letter path is also found unknown
        out = scrub_paths(message, known)
        assert "Secret" not in out and "sales" not in out and tmp_path.name not in out, out


ALL_FORMS = [WIN, WIN_FWD, UNC, UNC_FWD, *RELATIVE]
TEMPLATES = [
    "{p}",
    "[Errno 2] No such file or directory: '{p}'",
    "IO Error: Could not open file \"{p}\" for reading (line 4); try again later",
    "Failed to read {p} because the header is missing. Check the delimiter.",
]


@pytest.mark.parametrize("path", ALL_FORMS)
@pytest.mark.parametrize("template", TEMPLATES)
def test_a_known_path_is_removed_in_any_spelling_and_case(path, template):
    for spelled in (path, path.replace("\\", "\\\\"), path.replace("\\", "/"), path.replace("/", "\\"), path.upper(),
                    path.lower()):
        out = scrub_paths(template.format(p=spelled), [path])
        assert_no_path_left(out)
        for tail in ("(line 4); try again later", "Check the delimiter.", "header is missing"):
            if tail in template:
                assert tail in out                                     # the useful part of the message stays


@pytest.mark.parametrize("path", [WIN, WIN_FWD, UNC])
@pytest.mark.parametrize("quote", ["'", '"'])
def test_an_unknown_quoted_drive_or_unc_path_is_removed(path, quote):
    for spelled in (path, path.replace("\\", "\\\\")):                  # as typed, and as repr() shows it
        out = scrub_paths(f"[Errno 2] No such file: {quote}{spelled}{quote} (while reading; retry)")
        assert_no_path_left(out)
        assert out == f"[Errno 2] No such file: {quote}<file>{quote} (while reading; retry)"


@pytest.mark.parametrize("known", [
    r"C:\Users\Ven Nanduri\My Data\sales data",                         # spaces, no extension
    r"C:\Users\Ven Nanduri\My Data\sales data.csv",
    "/srv/uploads/My Folder/q_1",
    r"\\fileserver\finance share\report",
])
def test_known_typed_paths_with_spaces_and_no_extension_are_fully_scrubbed(known):
    for spelled in (known, known.replace("\\", "\\\\"), known.replace("\\", "/"), known.upper()):
        out = scrub_paths(f"cannot open {spelled} now: not found", [known])
        assert out == "cannot open <file> now: not found", out


def test_a_known_upload_path_is_scrubbed_but_text_around_it_is_not(tmp_path):
    upload = str(tmp_path / "truealign_uploads_ab12" / "quality_f00.csv")
    out = scrub_paths(f"Could not read {upload}: Debit / Credit missing", [upload])
    assert out == "Could not read <file>: Debit / Credit missing"


@pytest.mark.parametrize("known", ["", "/", "\\", "//"])
def test_a_degenerate_known_path_does_not_eat_ordinary_slashes(known):
    assert scrub_paths("N / A and a\\b", [known]) == "N / A and a\\b"


def test_two_paths_in_one_message_and_text_between_them_survives():
    out = scrub_paths(rf"cannot compare {WIN} with {UNC} because the keys differ", [WIN, UNC])
    assert_no_path_left(out)
    assert out == "cannot compare <file> with <file> because the keys differ"


@pytest.mark.parametrize("text", [
    r"Login failed for user 'CORP\jdoe'.",
    "Could not convert '2024/01/15' with format /%Y/%m/",
    r"Invalid escape '\N' in column; sniffed delimiter '\t'",
    "Use either and/or; N/A; 3/4 is fine; ratio 10/20",
    "https://example.com/files/report.html was slow",
    "Column 'a.b' not found. Available: ['x', 'y']",
    "Debit / Credit",
    "N / A",
    "Expected 3 / 4",
    r"CORP\jdoe",
    "Posted on 2024/01/15 and 15/01/2024 at 10:30",
    "see http://example.com/a/b.csv and https://host/x/y.xlsx?v=1",
    "Mismatch in 'Dr/Cr' for 'C: drive' and 'D:' totals",
    "path/like/but/unquoted.csv or ./rel/x.csv are not scrubbed unless known",
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
