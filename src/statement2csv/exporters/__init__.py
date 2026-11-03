"""Output formats. Add a new target by adding a module and an entry in ``EXPORTERS``."""

from statement2csv.exporters.base import (
    XLSX_INSTALL_HINT,
    Exporter,
    ExportResult,
    Skipped,
    Table,
    fmt_decimal,
)
from statement2csv.exporters.gains import GainsExporter
from statement2csv.exporters.ghostfolio import GhostfolioExporter
from statement2csv.exporters.spreadsheet import SpreadsheetExporter
from statement2csv.exporters.wealthfolio import WealthfolioExporter

EXPORTERS: dict[str, type[Exporter]] = {
    cls.name: cls
    for cls in (WealthfolioExporter, GhostfolioExporter, SpreadsheetExporter, GainsExporter)
}
#: Alternative ``--format`` names, e.g. ``csv`` for ``spreadsheet``.
ALIASES: dict[str, str] = {alias: cls.name for cls in EXPORTERS.values() for alias in cls.aliases}


def get_exporter(name: str, *, broker: str | None = None) -> Exporter:
    key = name.strip().lower()
    try:
        cls = EXPORTERS[ALIASES.get(key, key)]
    except KeyError:
        available = ", ".join([*EXPORTERS, *ALIASES])
        raise ValueError(f"unknown format {name!r}. Available: {available}") from None
    return cls(broker=broker)


__all__ = [
    "ALIASES",
    "EXPORTERS",
    "XLSX_INSTALL_HINT",
    "ExportResult",
    "Exporter",
    "GainsExporter",
    "GhostfolioExporter",
    "Skipped",
    "SpreadsheetExporter",
    "Table",
    "WealthfolioExporter",
    "fmt_decimal",
    "get_exporter",
]
