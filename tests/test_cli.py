from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from statement2csv.cli import app

runner = CliRunner()


def test_brokers_lists_registered_parser(dummy_parser) -> None:
    result = runner.invoke(app, ["brokers"])
    assert result.exit_code == 0
    assert "dummy" in result.output and "Dummy Broker" in result.output


def test_convert_auto_detect(dummy_parser, dummy_statement: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    args = ["convert", str(dummy_statement), "-f", "ghostfolio", "-o", str(out)]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[1] == "2024-01-15,AAPL,,USD,185.5,10,buy,4.95,"


def test_convert_unknown_broker(dummy_statement: Path) -> None:
    result = runner.invoke(app, ["convert", str(dummy_statement), "--broker", "nope"])
    assert result.exit_code == 1
    assert "unknown broker" in result.output


def test_convert_auto_is_case_insensitive(
    dummy_parser, dummy_statement: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out.csv"
    result = runner.invoke(app, ["convert", str(dummy_statement), "-b", "AUTO", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists()


def test_convert_spreadsheet_via_csv_alias_has_broker_column(
    dummy_parser, dummy_statement: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out.csv"
    result = runner.invoke(app, ["convert", str(dummy_statement), "-f", "csv", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "(Spreadsheet format)" in result.output
    lines = out.read_text(encoding="utf-8").splitlines()
    assert (
        lines[0]
        == "date,broker,account,type,symbol,description,quantity,price,amount,fees,currency"
    )
    assert lines[1] == "2024-01-15,Dummy Broker,,Buy,AAPL,,10,185.5,-1859.95,4.95,USD"


def test_convert_gains_prints_summary_disclaimer_and_basis_warning(
    dummy_parser, dummy_statement: Path, tmp_path: Path
) -> None:
    out = tmp_path / "gains.csv"
    result = runner.invoke(app, ["convert", str(dummy_statement), "-f", "gains", "-o", str(out)])
    assert result.exit_code == 0, result.output
    # The dummy statement only has a buy: header-only file, explained.
    assert out.read_text(encoding="utf-8").splitlines() == [
        "description,date_acquired,date_sold,proceeds,cost_basis,gain_loss,term"
    ]
    assert "no SELL activities found" in result.output
    assert "wrote 0 sale lots" in result.output
    assert "Not tax advice" in result.output and "1099-B is authoritative" in result.output
    assert "no sale lots;" in result.output


def test_default_output_names(dummy_parser, dummy_statement: Path) -> None:
    pytest.importorskip("openpyxl")
    result = runner.invoke(app, ["convert", str(dummy_statement), "-f", "spreadsheet"])
    assert result.exit_code == 0, result.output
    assert (dummy_statement.parent / "statement.spreadsheet.csv").exists()
    result = runner.invoke(app, ["convert", str(dummy_statement), "-f", "gains", "--xlsx"])
    assert result.exit_code == 0, result.output
    assert (dummy_statement.parent / "statement.gains.xlsx").exists()


def test_xlsx_output(dummy_parser, dummy_statement: Path, tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    out = tmp_path / "out.xlsx"
    args = ["convert", str(dummy_statement), "-f", "csv", "--xlsx", "-o", str(out)]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    ws = openpyxl.load_workbook(out).active
    assert ws["B2"].value == "Dummy Broker"
    assert ws["I2"].value == -1859.95


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["-f", "wealthfolio", "--xlsx"], "--xlsx works only with --format spreadsheet, gains"),
        (["-f", "spreadsheet", "--xlsx", "-o", "-"], "--xlsx cannot write to stdout"),
    ],
)
def test_xlsx_errors(dummy_parser, dummy_statement: Path, args, message) -> None:
    result = runner.invoke(app, ["convert", str(dummy_statement), *args])
    assert result.exit_code == 1
    assert message in result.output


def test_xlsx_without_openpyxl_explains_the_extra(
    dummy_parser, dummy_statement: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setitem(sys.modules, "openpyxl", None)  # makes `import openpyxl` fail
    out = tmp_path / "out.xlsx"
    args = ["convert", str(dummy_statement), "-f", "csv", "--xlsx", "-o", str(out)]
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert "pip install 'statement2csv[xlsx]'" in result.output
    assert not out.exists()
