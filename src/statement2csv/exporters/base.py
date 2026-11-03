"""Exporter interface: turn normalized activities into a table, written as CSV (or XLSX).

Most exporters map one activity to one row and only implement ``header`` and ``row``.
Exporters whose rows are not one-to-one with activities (e.g. a gains report) override
``build`` instead. Writing the table out is shared: ``export`` writes CSV and
``export_xlsx`` writes an Excel workbook (for exporters with ``supports_xlsx``).
"""

from __future__ import annotations

import csv
import datetime as dt
from abc import ABC
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import ClassVar, TextIO

from statement2csv.models import Activity

#: A table cell. Exporters may return typed values; CSV output formats them as text,
#: XLSX output keeps numbers and dates as real numbers and dates.
Cell = str | Decimal | dt.date | None

XLSX_INSTALL_HINT = "XLSX output needs openpyxl: pip install 'statement2csv[xlsx]'"


@dataclass
class Skipped:
    activity: Activity
    reason: str


@dataclass
class ExportResult:
    written: int = 0
    skipped: list[Skipped] = field(default_factory=list)
    #: Problems that are not about a single skipped row (shown as warnings).
    warnings: list[str] = field(default_factory=list)
    #: Extra lines to show the user after export (e.g. report totals, disclaimers).
    summary: list[str] = field(default_factory=list)


@dataclass
class Table:
    header: list[str]
    rows: list[Mapping[str, Cell]]
    result: ExportResult


def fmt_decimal(value: Decimal | None) -> str:
    """Plain decimal notation, no exponent, no trailing zeros. ``None`` becomes ``""``."""
    if value is None:
        return ""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def fmt_cell(value: Cell) -> str:
    """CSV text for a table cell."""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return fmt_decimal(value)
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


class Exporter(ABC):
    name: ClassVar[str]
    display_name: ClassVar[str]
    #: Other ``--format`` names accepted for this exporter.
    aliases: ClassVar[tuple[str, ...]] = ()
    #: Whether ``export_xlsx`` makes sense for this format (import formats need CSV).
    supports_xlsx: ClassVar[bool] = False
    #: What one output row is, for the CLI summary ("wrote 5 activities").
    row_noun: ClassVar[str] = "activities"
    #: Excel number formats for some columns in XLSX output, e.g. ``{"amount": "0.00"}``.
    xlsx_number_formats: ClassVar[Mapping[str, str]] = {}

    def __init__(self, *, broker: str | None = None) -> None:
        #: Display name of the broker the activities came from, if known.
        self.broker = broker

    def header(self, activities: Sequence[Activity]) -> list[str]:
        """Column names for this export (may depend on the data, e.g. optional account)."""
        raise NotImplementedError

    def row(self, activity: Activity, header: Sequence[str]) -> Mapping[str, Cell] | str:
        """Return a ``{column: value}`` row, or a string reason to skip the activity."""
        raise NotImplementedError

    def format_cell(self, value: Cell) -> str:
        """CSV text for a cell. Override to change e.g. how numbers are written."""
        return fmt_cell(value)

    def build(self, activities: Iterable[Activity]) -> Table:
        """Build the output table. The default calls ``header`` and ``row`` per activity."""
        items = sorted(activities, key=lambda a: a.date)
        header = self.header(items)
        result = ExportResult()
        rows: list[Mapping[str, Cell]] = []
        for activity in items:
            row = self.row(activity, header)
            if isinstance(row, str):
                result.skipped.append(Skipped(activity, row))
                continue
            rows.append(row)
        result.written = len(rows)
        return Table(header, rows, result)

    def export(self, activities: Iterable[Activity], stream: TextIO) -> ExportResult:
        table = self.build(activities)
        writer = csv.DictWriter(stream, fieldnames=table.header, lineterminator="\n")
        writer.writeheader()
        for row in table.rows:
            writer.writerow({k: self.format_cell(v) for k, v in row.items()})
        return table.result

    def export_xlsx(self, activities: Iterable[Activity], path: Path) -> ExportResult:
        """Write an Excel workbook. Raises ``ImportError`` if openpyxl isn't installed."""
        if not self.supports_xlsx:
            raise ValueError(f"{self.display_name} output is CSV only")
        try:
            from openpyxl import Workbook
            from openpyxl.utils import get_column_letter
        except ImportError as exc:
            raise ImportError(XLSX_INSTALL_HINT) from exc

        table = self.build(activities)
        wb = Workbook()
        ws = wb.active
        ws.title = self.display_name[:31]
        ws.append(table.header)
        widths = [len(h) for h in table.header]
        for row in table.rows:
            values = [row.get(column) for column in table.header]
            ws.append([None if v == "" else v for v in values])
            for i, v in enumerate(values):
                widths[i] = max(widths[i], len(self.format_cell(v)))
        for column, cells in zip(table.header, ws.iter_cols(min_row=2), strict=True):
            for c in cells:
                if isinstance(c.value, dt.date):
                    c.number_format = "yyyy-mm-dd"
                elif column in self.xlsx_number_formats and isinstance(c.value, Decimal):
                    c.number_format = self.xlsx_number_formats[column]
        for i, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = min(width + 2, 60)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        if table.result.summary:
            notes = wb.create_sheet("Summary")
            for line in table.result.summary:
                notes.append([line])
            notes.column_dimensions["A"].width = 100
        wb.save(path)
        return table.result
