"""Every workbook the app hands out arrives as a readable table.

The point of these is that a planner opens the file and can work: headings
that stay put while scrolling, columns wide enough to read, numbers with a
sensible number of decimals, and filter buttons where you expect them.
"""
from __future__ import annotations

import io

import openpyxl
import pandas as pd

from core import xlsx


def _frame(n=5):
    return pd.DataFrame({
        "item_code": [f"code{i}" for i in range(n)],
        "description": [f"A material with a fairly long name {i}"
                        for i in range(n)],
        "count": range(n),
        "rate": [0.004739 + i / 10000 for i in range(n)],
    })


def _load(frames, groups=None):
    book = xlsx.to_bytes(frames, groups)
    return openpyxl.load_workbook(io.BytesIO(book))


# --- the table itself ---------------------------------------------------------

def test_each_sheet_becomes_a_real_excel_table():
    """A table, not a matrix of data: banded rows and filter buttons on every
    heading, which is what makes a 9,000-row sheet workable."""
    ws = _load({"forecasts": _frame()})["forecasts"]

    assert len(ws.tables) == 1
    table = ws.tables[list(ws.tables)[0]]
    assert table.ref == "A1:D6"                 # header + 5 rows
    assert table.tableStyleInfo.showRowStripes


def test_the_heading_row_is_frozen():
    ws = _load({"forecasts": _frame(200)})["forecasts"]
    assert ws.freeze_panes == "A2"


def test_the_heading_row_is_styled():
    ws = _load({"forecasts": _frame()})["forecasts"]
    heading = ws.cell(row=1, column=1)
    assert heading.font.bold
    assert heading.fill.fgColor.rgb.endswith(xlsx.HEADER_FILL.fgColor.rgb[-6:])


def test_an_empty_sheet_keeps_a_filter_and_never_a_broken_table():
    """Excel rejects a table over a header-only range — writing one anyway
    produces a file Excel offers to repair."""
    ws = _load({"empty": _frame(0)})["empty"]
    assert not ws.tables
    assert ws.auto_filter.ref == "A1:D1"


def test_table_names_are_unique_and_legal():
    book = _load({"data dictionary": _frame(), "1st sheet": _frame()})
    names = [n for ws in book.worksheets for n in ws.tables]
    assert len(names) == len(set(names))
    for name in names:
        assert not name[0].isdigit()
        assert all(c.isalnum() or c == "_" for c in name)


# --- widths -------------------------------------------------------------------

def test_columns_are_sized_from_their_contents():
    ws = _load({"s": _frame()})["s"]
    widths = {ws.cell(row=1, column=i).value:
              ws.column_dimensions[chr(64 + i)].width
              for i in range(1, 5)}

    assert widths["description"] > widths["item_code"]
    assert all(xlsx.MIN_WIDTH <= w <= xlsx.MAX_WIDTH for w in widths.values())


def test_a_very_long_text_column_wraps_instead_of_stretching():
    frame = pd.DataFrame({"note": ["x" * 400], "n": [1]})
    ws = _load({"s": frame})["s"]

    assert ws.column_dimensions["A"].width == xlsx.MAX_WIDTH
    assert ws.cell(row=2, column=1).alignment.wrap_text
    assert not ws.cell(row=2, column=2).alignment.wrap_text


def test_a_short_column_is_still_wide_enough_to_read_its_heading():
    frame = pd.DataFrame({"a_rather_long_heading": [1, 2]})
    ws = _load({"s": frame})["s"]
    assert ws.column_dimensions["A"].width >= len("a_rather_long_heading")


# --- numbers ------------------------------------------------------------------

def test_whole_numbers_get_no_decimals():
    ws = _load({"s": pd.DataFrame({"n": [1, 20, 300]})})["s"]
    assert ws.cell(row=2, column=1).number_format == "#,##0"


def _decimals(fmt: str) -> int:
    return len(fmt.split(".")[1]) if "." in fmt else 0


def test_a_small_rate_keeps_its_significant_digits():
    """0.004739 shown as 0.00 is not a number anyone can use."""
    ws = _load({"s": pd.DataFrame({"rate": [0.004739, 0.005528]})})["s"]
    assert _decimals(ws.cell(row=2, column=1).number_format) >= 5


def test_a_large_quantity_does_not_get_six_decimals():
    ws = _load({"s": pd.DataFrame({"demand": [1234.5, 9876.25]})})["s"]
    assert _decimals(ws.cell(row=2, column=1).number_format) == 2


def test_a_tiny_value_is_never_rounded_to_a_flat_zero():
    """A p-value printed as 0.0000 reads as 'no effect' when it means the
    opposite."""
    values = pd.Series([0.4, 0.3, 0.35, 0.000002])
    fmt = xlsx._number_format(values)
    decimals = len(fmt.split(".")[1])
    assert decimals >= 6
    assert round(0.000002, decimals) > 0


def test_one_outlier_does_not_drag_a_whole_column():
    """The typical value sets the decimals, not the extreme one — otherwise
    a single near-zero row gives every other row six decimal places."""
    ordinary = xlsx._number_format(pd.Series([120.5, 130.25, 125.75]))
    assert _decimals(ordinary) == xlsx.MIN_DECIMALS


def test_a_fractional_column_never_rounds_to_whole_numbers():
    """1234.5 is four significant digits away from 1235, and a quantity that
    arrives without its decimals cannot be got back."""
    fmt = xlsx._number_format(pd.Series([1234.5, 9876.25]))
    assert _decimals(fmt) >= xlsx.MIN_DECIMALS
    assert fmt == "#,##0.00"


def test_text_columns_are_left_alone():
    ws = _load({"s": pd.DataFrame({"t": ["a", "b"]})})["s"]
    assert ws.cell(row=2, column=1).number_format == "General"


def test_an_all_null_numeric_column_does_not_crash():
    ws = _load({"s": pd.DataFrame({"n": [None, None]})})["s"]
    assert ws.max_row == 3


# --- grouped formats ----------------------------------------------------------

def test_a_value_and_its_interval_bounds_share_one_format():
    """Formatting them independently gives the value three decimals and its
    own upper bound five, which is what makes a sheet look dumped."""
    frame = pd.DataFrame({
        "target_value": [0.004739, 0.005528],
        "lower_80": [0.003332, 0.004314],
        "upper_95": [0.006992, 0.007496],
        "driver_plan": [26.7, 28.0],
    })
    groups = [("target_value", "lower_80", "upper_95")]
    ws = _load({"forecasts": frame}, groups)["forecasts"]

    formats = [ws.cell(row=2, column=i).number_format for i in range(1, 4)]
    assert len(set(formats)) == 1, formats
    # a column outside the group keeps its own scale
    assert ws.cell(row=2, column=4).number_format != formats[0]


def test_a_group_naming_absent_columns_is_ignored():
    frame = pd.DataFrame({"a": [1.5, 2.5]})
    assert xlsx.shared_formats(frame, [("a", "missing")]) == {}
    assert xlsx.shared_formats(frame, [("nope", "gone")]) == {}


# --- values are untouched -----------------------------------------------------

def test_formatting_never_changes_a_value():
    frame = _frame(20)
    book = xlsx.to_bytes({"s": frame})
    read_back = pd.read_excel(io.BytesIO(book), sheet_name="s")

    pd.testing.assert_frame_equal(read_back, frame, check_dtype=False)


def test_a_long_sheet_name_is_truncated_to_excels_limit():
    book = _load({"a_very_long_sheet_name_beyond_the_limit": _frame()})
    assert book.sheetnames == ["a_very_long_sheet_name_beyond_t"]
    assert all(len(n) <= 31 for n in book.sheetnames)


def test_to_file_writes_the_same_bytes_as_to_bytes(tmp_path):
    frames = {"s": _frame()}
    path = xlsx.to_file(frames, tmp_path / "nested" / "out.xlsx")
    assert path.exists()
    assert path.read_bytes() == xlsx.to_bytes(frames)
