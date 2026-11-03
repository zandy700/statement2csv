"""Exporter interface: turn normalized activities into a target app's CSV."""

from __future__ import annotations

import csv
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import ClassVar, TextIO

from statement2csv.models import Activity


@dataclass
class Skipped:
    activity: Activity
    reason: str


@dataclass
class ExportResult:
    written: int = 0
    skipped: list[Skipped] = field(default_factory=list)


def fmt_decimal(value: Decimal | None) -> str:
    """Plain decimal notation, no exponent, no trailing zeros. ``None`` becomes ``""``."""
    if value is None:
        return ""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


class Exporter(ABC):
    name: ClassVar[str]
    display_name: ClassVar[str]

    @abstractmethod
    def header(self, activities: Sequence[Activity]) -> list[str]:
        """Column names for this export (may depend on the data, e.g. optional account)."""

    @abstractmethod
    def row(self, activity: Activity, header: Sequence[str]) -> dict[str, str] | str:
        """Return a ``{column: value}`` row, or a string reason to skip the activity."""

    def export(self, activities: Iterable[Activity], stream: TextIO) -> ExportResult:
        items = sorted(activities, key=lambda a: a.date)
        header = self.header(items)
        writer = csv.DictWriter(stream, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        result = ExportResult()
        for activity in items:
            row = self.row(activity, header)
            if isinstance(row, str):
                result.skipped.append(Skipped(activity, row))
                continue
            writer.writerow(row)
            result.written += 1
        return result
