from __future__ import annotations

from pathlib import Path

import pytest

from statement2csv.parsers import (
    BrokerParser,
    ParserError,
    all_parsers,
    detect_parser,
    get_parser,
    unregister,
)


def test_discovery_imports_package_without_error() -> None:
    parsers = all_parsers()
    assert all(issubclass(cls, BrokerParser) for cls in parsers.values())
    assert "dummy" not in parsers


def test_subclass_registers_and_is_detected(dummy_parser, dummy_statement: Path) -> None:
    assert all_parsers()["dummy"] is dummy_parser
    assert isinstance(get_parser("dummy"), dummy_parser)
    assert isinstance(detect_parser(dummy_statement), dummy_parser)


def test_detect_skips_other_suffixes(dummy_parser, tmp_path: Path) -> None:
    other = tmp_path / "statement.pdf"
    other.write_text("DUMMY BROKER\n", encoding="utf-8")
    with pytest.raises(ParserError, match="could not detect"):
        detect_parser(other)


def test_unknown_broker() -> None:
    with pytest.raises(ParserError, match="unknown broker"):
        get_parser("nope")


def test_duplicate_name_rejected(dummy_parser) -> None:
    with pytest.raises(TypeError, match="duplicate parser name"):

        class Clash(BrokerParser):
            name = "dummy"
            display_name = "Clash"

            def detect(self, path: Path) -> bool:
                return False

            def parse(self, path: Path) -> list:
                return []


def test_missing_name_rejected() -> None:
    with pytest.raises(TypeError, match="'name'"):

        class Nameless(BrokerParser):
            display_name = "Nameless"

            def detect(self, path: Path) -> bool:
                return False

            def parse(self, path: Path) -> list:
                return []

    unregister("nameless")
