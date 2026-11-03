"""Output formats. Add a new target by adding a module and an entry in ``EXPORTERS``."""

from statement2csv.exporters.base import Exporter, ExportResult, Skipped, fmt_decimal
from statement2csv.exporters.ghostfolio import GhostfolioExporter
from statement2csv.exporters.wealthfolio import WealthfolioExporter

EXPORTERS: dict[str, type[Exporter]] = {
    cls.name: cls for cls in (WealthfolioExporter, GhostfolioExporter)
}


def get_exporter(name: str) -> Exporter:
    try:
        return EXPORTERS[name.lower()]()
    except KeyError:
        raise ValueError(f"unknown format {name!r}. Available: {', '.join(EXPORTERS)}") from None


__all__ = [
    "EXPORTERS",
    "ExportResult",
    "Exporter",
    "GhostfolioExporter",
    "Skipped",
    "WealthfolioExporter",
    "fmt_decimal",
    "get_exporter",
]
