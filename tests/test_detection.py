from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from statement2csv.parsers import ParserError, detect_parser
from statement2csv.parsers.fidelity import FidelityParser
from statement2csv.parsers.robinhood import RobinhoodParser
from statement2csv.parsers.schwab import SchwabParser

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_FILES = {
    "fidelity": FIXTURES / "fidelity_statement.pdf",
    "schwab": FIXTURES / "schwab_statement.pdf",
    "robinhood": FIXTURES / "robinhood_activity.csv",
}
PARSERS = {"fidelity": FidelityParser, "schwab": SchwabParser, "robinhood": RobinhoodParser}

GHOSTFOLIO_HEADER = "Date,Code,DataSource,Currency,Price,Quantity,Action,Fee,Note\n"


@pytest.mark.parametrize("fixture", FIXTURE_FILES)
@pytest.mark.parametrize("parser", PARSERS)
def test_detect_matrix(parser: str, fixture: str) -> None:
    assert PARSERS[parser]().detect(FIXTURE_FILES[fixture]) is (parser == fixture)


@pytest.mark.parametrize("fixture", FIXTURE_FILES)
def test_auto_detect_picks_the_right_parser(fixture: str) -> None:
    assert detect_parser(FIXTURE_FILES[fixture]).name == fixture


def _trivial_pdf(path: Path) -> Path:
    c = canvas.Canvas(str(path), pagesize=letter, invariant=1)
    c.drawString(72, 700, "Notes on funds: FIDELITY CONTRAFUND and SCHWAB US DIVIDEND EQUITY ETF")
    c.drawString(72, 680, "Plain document without any statement markers.")
    c.save()
    return path


def _bad_inputs(tmp_path: Path) -> dict[str, Path]:
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_text("this is not a pdf", encoding="utf-8")
    random_pdf = tmp_path / "random.pdf"
    random_pdf.write_bytes(bytes(range(256)) * 20)
    random_csv = tmp_path / "random.csv"
    random_csv.write_bytes(bytes(range(256)) * 20)
    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_bytes(b"")
    ghostfolio = tmp_path / "ghostfolio.csv"
    ghostfolio.write_text(GHOSTFOLIO_HEADER + "2024-01-15,AAPL,,USD,185.5,10,buy,4.95,\n")
    return {
        "empty-pdf": empty,
        "empty-csv": empty_csv,
        "fake-pdf": fake_pdf,
        "random-pdf": random_pdf,
        "random-csv": random_csv,
        "missing": tmp_path / "does-not-exist.pdf",
        "missing-csv": tmp_path / "does-not-exist.csv",
        "ghostfolio-csv": ghostfolio,
        "trivial-pdf": _trivial_pdf(tmp_path / "trivial.pdf"),
    }


BAD_NAMES = [
    "empty-pdf",
    "empty-csv",
    "fake-pdf",
    "random-pdf",
    "random-csv",
    "missing",
    "missing-csv",
    "ghostfolio-csv",
    "trivial-pdf",
]


@pytest.mark.parametrize("name", BAD_NAMES)
@pytest.mark.parametrize("parser", PARSERS)
def test_detect_false_and_never_raises_on_foreign_input(
    tmp_path: Path, parser: str, name: str
) -> None:
    assert PARSERS[parser]().detect(_bad_inputs(tmp_path)[name]) is False


@pytest.mark.parametrize("name", BAD_NAMES)
def test_auto_detect_fails_cleanly_on_foreign_input(tmp_path: Path, name: str) -> None:
    with pytest.raises(ParserError, match="could not detect"):
        detect_parser(_bad_inputs(tmp_path)[name])


def test_directory_is_not_detected(tmp_path: Path) -> None:
    for cls in PARSERS.values():
        assert cls().detect(tmp_path) is False
