"""Excel output that reads like a report rather than a dump.

Every workbook the app hands a user goes through here, so a download from the
browser, from `ForecastLens --export` and from the CLI are the same file.

What it does to each sheet:

  - turns the range into a real Excel **table**, so it arrives banded, with
    filter buttons on every heading and a name Excel can refer to;
  - freezes the heading row, so scrolling 9,000 forecast rows never loses the
    column names;
  - sets each column's width from what is actually in it, and wraps the long
    prose columns instead of stretching them off the screen;
  - gives numeric columns a format chosen from their own magnitude — a
    consumption rate of 0.004739 and a demand of 12,400 cannot share one
    fixed decimal count.

Nothing here changes a value. Formatting is presentation; the numbers are
written by pandas exactly as they were computed.
"""
from __future__ import annotations

import io
import math
import re
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

#: banded rows, no column banding — readable without looking decorated
TABLE_STYLE = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True,
                             showColumnStripes=False, showFirstColumn=False,
                             showLastColumn=False)

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(color="FFFFFF", bold=True)
HEADER_ALIGN = Alignment(horizontal="left", vertical="center", wrap_text=True)
WRAP_TOP = Alignment(vertical="top", wrap_text=True)
THIN_BOTTOM = Border(bottom=Side(style="thin", color="BFBFBF"))

#: width bounds, in Excel character units
MIN_WIDTH = 10
MAX_WIDTH = 46
#: a column whose content is longer than this wraps rather than stretching
WRAP_ABOVE = 46
#: rows sampled when measuring a column — enough to be representative without
#: walking 9,000 rows per column
WIDTH_SAMPLE = 300
#: numeric formats are chosen for about this many significant digits, matching
#: what the charts show on hover
SIGNIFICANT_DIGITS = 4
MAX_DECIMALS = 6
#: a column that holds fractions never rounds to whole numbers: four
#: significant digits of 1234.5 is 1235, and a demand that arrives without its
#: decimals cannot be recovered by widening the column
MIN_DECIMALS = 2


def _table_name(sheet: str, used: set[str]) -> str:
    """A name Excel will accept: letters, digits and underscores, never
    starting with a digit, unique in the workbook."""
    base = re.sub(r"\W", "_", sheet) or "table"
    if base[0].isdigit():
        base = f"t_{base}"
    name, n = base, 1
    while name.lower() in used:
        n += 1
        name = f"{base}_{n}"
    used.add(name.lower())
    return name


def _number_format(*columns: pd.Series) -> str | None:
    """A format for one numeric column — or for several that must share one.

    Whole numbers get thousands separators and no decimals. Everything else
    gets enough decimals to show ~4 significant digits of a TYPICAL value:
    the median, not the minimum, so a single tiny outlier cannot drag a whole
    column to six decimal places. The count is then widened if it would round
    the smallest real value to a flat zero, because a p-value printed as
    0.0000 reads as "no effect" when it means the opposite.
    """
    numeric = pd.concat([pd.to_numeric(c, errors="coerce") for c in columns],
                        ignore_index=True).dropna()
    if numeric.empty:
        return None
    if ((numeric % 1) == 0).all():
        return "#,##0"
    magnitudes = numeric.abs()
    magnitudes = magnitudes[magnitudes > 0]
    if magnitudes.empty:
        return "#,##0.00"

    typical = SIGNIFICANT_DIGITS - 1 - math.floor(math.log10(
        float(magnitudes.median())))
    readable = -math.floor(math.log10(float(magnitudes.min())))
    decimals = min(MAX_DECIMALS, max(MIN_DECIMALS, typical, readable))
    return "#,##0." + "0" * decimals


def shared_formats(frame: pd.DataFrame,
                   groups: list[tuple[str, ...]]) -> dict[str, str]:
    """One number format per group of columns that measure the same thing.

    A forecast and its four interval bounds are one quantity seen five ways.
    Formatting them independently gives the value three decimals and its own
    upper bound five, which is exactly what makes a sheet look like it was
    dumped rather than written.
    """
    out: dict[str, str] = {}
    for group in groups:
        present = [c for c in group if c in frame.columns
                   and pd.api.types.is_numeric_dtype(frame[c])]
        if len(present) < 2:
            continue
        fmt = _number_format(*(frame[c] for c in present))
        if fmt:
            out.update({c: fmt for c in present})
    return out


def _column_width(header: str, values: pd.Series) -> tuple[float, bool]:
    """(width, wrap). Measured from the heading and a sample of the data."""
    sample = values.head(WIDTH_SAMPLE).dropna()
    longest = max((len(str(v)) for v in sample), default=0)
    needed = max(len(str(header)), longest) + 2
    if needed > WRAP_ABOVE:
        return MAX_WIDTH, True
    return max(MIN_WIDTH, min(MAX_WIDTH, float(needed))), False


def style_sheet(worksheet, frame: pd.DataFrame, table_name: str,
                formats: dict[str, str] | None = None) -> None:
    """Apply the whole treatment to one already-written sheet.

    `formats` pins the number format of named columns, overriding what would
    be inferred from each column alone — used to keep a value and its
    interval bounds on one format.
    """
    n_rows, n_cols = len(frame), len(frame.columns)
    if n_cols == 0:
        return
    formats = formats or {}

    for index, header in enumerate(frame.columns, start=1):
        cell = worksheet.cell(row=1, column=index)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BOTTOM

        column = frame[header]
        width, wrap = _column_width(header, column)
        letter = get_column_letter(index)
        worksheet.column_dimensions[letter].width = width

        fmt = formats.get(header)
        if fmt is None and pd.api.types.is_numeric_dtype(column):
            fmt = _number_format(column)
        # Only wrapped columns need an explicit alignment; Excel's default
        # already reads correctly for everything else, and on a 9,000-row
        # export an alignment object per cell is real time for no gain.
        if fmt or wrap:
            for row in range(2, n_rows + 2):
                body = worksheet.cell(row=row, column=index)
                if wrap:
                    body.alignment = WRAP_TOP
                if fmt:
                    body.number_format = fmt

    worksheet.freeze_panes = "A2"
    if n_rows:
        # A real table brings its own filter buttons and banding. Excel
        # rejects a table over a header-only range, so an empty sheet keeps
        # the styled heading and nothing else.
        ref = f"A1:{get_column_letter(n_cols)}{n_rows + 1}"
        table = Table(displayName=table_name, ref=ref)
        table.tableStyleInfo = TABLE_STYLE
        worksheet.add_table(table)
    else:
        worksheet.auto_filter.ref = f"A1:{get_column_letter(n_cols)}1"


def write_sheets(frames: dict[str, pd.DataFrame], writer,
                 groups: list[tuple[str, ...]] | None = None) -> None:
    """Write every frame through an open pandas ExcelWriter and format it.

    `groups` names sets of columns that measure the same quantity and must
    therefore share one number format. Columns not in any group are formatted
    from their own contents.
    """
    used_names: set[str] = set()
    for name, frame in frames.items():
        sheet = name[:31]
        frame.to_excel(writer, sheet_name=sheet, index=False)
        style_sheet(writer.sheets[sheet], frame,
                    _table_name(sheet, used_names),
                    formats=shared_formats(frame, groups or []))


def to_bytes(frames: dict[str, pd.DataFrame],
             groups: list[tuple[str, ...]] | None = None) -> bytes:
    """A formatted workbook in memory — what a download button serves."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        write_sheets(frames, writer, groups)
    return buffer.getvalue()


def to_file(frames: dict[str, pd.DataFrame], path: str | Path,
            groups: list[tuple[str, ...]] | None = None) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(to_bytes(frames, groups))
    return target
