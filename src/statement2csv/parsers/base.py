"""Broker parser interface and registry.

To add a broker, drop one module into ``statement2csv/parsers/`` with a concrete
``BrokerParser`` subclass. Subclasses register themselves on definition, and
``discover()`` imports every module in the package, so you don't edit anything else::

    class MyBrokerParser(BrokerParser):
        name = "mybroker"
        display_name = "My Broker"

        def detect(self, path: Path) -> bool: ...
        def parse(self, path: Path) -> list[Activity]: ...
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from statement2csv.models import Activity

_REGISTRY: dict[str, type[BrokerParser]] = {}
_discovered = False


class ParserError(Exception):
    """Raised when a file can't be parsed or no/ambiguous parser matches."""


class BrokerParser(ABC):
    #: Unique CLI identifier: lowercase, no spaces (e.g. ``"degiro"``).
    name: ClassVar[str]
    #: Human-readable name (e.g. ``"DEGIRO"``).
    display_name: ClassVar[str]
    #: File suffixes this parser handles. Used to skip ``detect`` cheaply.
    file_types: ClassVar[tuple[str, ...]] = (".pdf",)

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if inspect.isabstract(cls):
            return
        register(cls)

    def accepts(self, path: Path) -> bool:
        """Cheap pre-check before ``detect``: is the file suffix one we handle?"""
        return path.suffix.lower() in self.file_types

    @abstractmethod
    def detect(self, path: Path) -> bool:
        """Return True if ``path`` looks like a statement from this broker.

        Must be fast, must not raise for files from other brokers, and must stay offline.
        """

    @abstractmethod
    def parse(self, path: Path) -> list[Activity]:
        """Extract all activities from ``path``. Raise ``ParserError`` on bad input."""


def register(cls: type[BrokerParser]) -> type[BrokerParser]:
    """Add a parser class to the registry. Called automatically for subclasses."""
    for attr in ("name", "display_name"):
        value = getattr(cls, attr, None)
        if not isinstance(value, str) or not value.strip():
            raise TypeError(f"{cls.__qualname__} must define a non-empty class attribute {attr!r}")
    if cls.name != cls.name.lower() or " " in cls.name or cls.name == "auto":
        raise TypeError(f"invalid parser name {cls.name!r}: use lowercase, no spaces, not 'auto'")
    existing = _REGISTRY.get(cls.name)
    if existing is not None and existing is not cls:
        raise TypeError(
            f"duplicate parser name {cls.name!r}: "
            f"{existing.__module__}.{existing.__qualname__} and {cls.__module__}.{cls.__qualname__}"
        )
    _REGISTRY[cls.name] = cls
    return cls


def unregister(name: str) -> None:
    """Remove a parser from the registry (mainly for tests)."""
    _REGISTRY.pop(name, None)


def discover() -> None:
    """Import every module in the ``statement2csv.parsers`` package (once)."""
    global _discovered
    if _discovered:
        return
    package = importlib.import_module("statement2csv.parsers")
    for module in pkgutil.iter_modules(package.__path__, prefix=f"{package.__name__}."):
        if module.name.rsplit(".", 1)[-1].startswith("_") or module.name == __name__:
            continue
        importlib.import_module(module.name)
    _discovered = True


def all_parsers() -> dict[str, type[BrokerParser]]:
    """All registered parser classes, sorted by name."""
    discover()
    return dict(sorted(_REGISTRY.items()))


def get_parser(name: str) -> BrokerParser:
    """Return a parser instance by name, or raise ``ParserError``."""
    parsers = all_parsers()
    try:
        return parsers[name.lower()]()
    except KeyError:
        known = ", ".join(parsers) or "(none installed)"
        raise ParserError(f"unknown broker {name!r}. Available: {known}") from None


def detect_parser(path: Path) -> BrokerParser:
    """Return the single parser whose ``detect`` accepts ``path``.

    Raises ``ParserError`` if no parser, or more than one, matches.
    """
    matches: list[BrokerParser] = []
    for cls in all_parsers().values():
        parser = cls()
        if not parser.accepts(path):
            continue
        try:
            if parser.detect(path):
                matches.append(parser)
        except Exception:  # a broken detector must not block the others
            continue
    if not matches:
        raise ParserError(
            f"could not detect the broker for {path.name}. "
            "Pass --broker explicitly (see `statement2csv brokers`)."
        )
    if len(matches) > 1:
        names = ", ".join(p.name for p in matches)
        raise ParserError(f"{path.name} matches several brokers ({names}). Pass --broker.")
    return matches[0]
