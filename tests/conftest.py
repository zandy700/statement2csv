from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest

from statement2csv.models import Activity, ActivityType
from statement2csv.parsers import BrokerParser, unregister


class DummyParser(BrokerParser):
    """Test-only parser: matches .txt files whose first line is DUMMY BROKER."""

    name = "dummy"
    display_name = "Dummy Broker"
    file_types = (".txt",)

    def detect(self, path: Path) -> bool:
        return path.read_text(encoding="utf-8").startswith("DUMMY BROKER")

    def parse(self, path: Path) -> list[Activity]:
        return [
            Activity(
                date=dt.date(2024, 1, 15),
                symbol="AAPL",
                activity_type=ActivityType.BUY,
                quantity=Decimal(10),
                unit_price=Decimal("185.50"),
                fee=Decimal("4.95"),
                currency="USD",
            )
        ]


# The class registers itself on definition. Keep it out of the registry by default
# so other tests see only the real parsers.
unregister(DummyParser.name)


@pytest.fixture
def dummy_parser() -> Iterator[type[DummyParser]]:
    from statement2csv.parsers import register

    register(DummyParser)
    yield DummyParser
    unregister(DummyParser.name)


@pytest.fixture
def dummy_statement(tmp_path: Path) -> Path:
    path = tmp_path / "statement.txt"
    path.write_text("DUMMY BROKER\n", encoding="utf-8")
    return path
