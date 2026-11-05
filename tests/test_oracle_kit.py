"""The Oracle test kit (samples/oracle_test_setup.sql) run through all three engines.

The rows are read from the SQL script itself, so this test, the script and the expected
results in the README can't drift apart. CHAR columns are padded to their declared width,
as Oracle stores them. Pushdown runs on SQLite here; the same data was validated by hand
against Oracle Database Free.
"""
import re
from pathlib import Path

import pandas as pd
import pytest

from conftest import ENGINES, config

KIT = Path(__file__).resolve().parents[1] / "samples" / "oracle_test_setup.sql"

SOURCE_COLS = ["INVOICE_NO", "SUPPLIER_NAME", "AMOUNT", "INVOICE_DATE", "STATUS", "REMARK"]
TARGET_COLS = ["INV_NUMBER", "VENDOR_NAME", "GROSS_AMT", "INV_DATE", "INV_STATUS", "COMMENTS"]
CHAR_WIDTHS = {"INVOICE_NO": 10, "SUPPLIER_NAME": 30}  # CHAR(n) columns in SRC_INVOICES

_VALUE = re.compile(r"(?:DATE|TIMESTAMP)\s+'([^']*)'|'((?:[^']|'')*)'|(NULL)|(-?\d+(?:\.\d+)?)")


def _parse_values(text: str) -> list:
    values = []
    for date_lit, str_lit, null, number in _VALUE.findall(text):
        if date_lit:
            values.append(date_lit)
        elif null:
            values.append(None)
        elif number:
            values.append(float(number) if "." in number else int(number))
        else:
            values.append(str_lit.replace("''", "'"))
    return values


def load_kit():
    rows = {"SRC_INVOICES": [], "TGT_INVOICES": []}
    for table, values in re.findall(r"INSERT INTO (\w+) VALUES \((.*)\);", KIT.read_text(encoding="utf-8")):
        rows[table].append(_parse_values(values))
    source = pd.DataFrame(rows["SRC_INVOICES"], columns=SOURCE_COLS)
    target = pd.DataFrame(rows["TGT_INVOICES"], columns=TARGET_COLS)
    for col, width in CHAR_WIDTHS.items():
        source[col] = source[col].map(lambda v: v if v is None else v.ljust(width))
    target["GROSS_AMT"] = target["GROSS_AMT"].astype(str)  # VARCHAR2 in the target table
    return source, target


# The mapping the README tells you to use (and that Claude Sonnet 5 suggested in the live test)
KIT_CONFIG = config(
    ["INVOICE_NO"],
    ("INVOICE_NO", "INV_NUMBER"),
    ("SUPPLIER_NAME", "VENDOR_NAME"),
    ("AMOUNT", "GROSS_AMT", "within 1%"),
    ("INVOICE_DATE", "INV_DATE"),
    ("STATUS", "INV_STATUS", "ignore case"),
    ("REMARK", "COMMENTS"),
)


def test_kit_parses_as_documented():
    source, target = load_kit()
    assert (len(source), len(target)) == (11, 12)
    assert source["INVOICE_NO"].str.len().eq(10).all()  # CHAR(10) padding is preserved


@pytest.mark.parametrize("engine", ENGINES)
def test_oracle_kit_expected_results(run, engine):
    source, target = load_kit()
    res = run(engine, source, target, KIT_CONFIG)

    assert (res.total_source, res.total_target) == (11, 12)
    assert res.matched_rows == 6          # INV001-003, INV005, INV007, INV008
    assert res.mismatched_rows == 3
    assert sorted(res.mismatches["INVOICE_NO"].str.strip()) == ["INV004", "INV006", "INV009"]
    assert res.missing_in_target_count == 1
    assert list(res.missing_in_target["INVOICE_NO"].str.strip()) == ["INV010"]
    assert res.missing_in_source_count == 1
    assert list(res.missing_in_source["INV_NUMBER"].str.strip()) == ["INV011"]
    assert res.duplicate_key_count == 1
    assert list(res.duplicate_keys["INVOICE_NO"]) == ["INV012"]

    by_invoice = {k.strip(): c for k, c in zip(res.mismatches["INVOICE_NO"], res.mismatches["Column"])}
    assert by_invoice == {"INV004": "REMARK -> COMMENTS",
                          "INV006": "AMOUNT -> GROSS_AMT",
                          "INV009": "SUPPLIER_NAME -> VENDOR_NAME"}
