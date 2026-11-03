"""Convert broker statements into Wealthfolio / Ghostfolio import CSVs."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("statement2csv")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0"
