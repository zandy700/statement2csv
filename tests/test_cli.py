from __future__ import annotations

from pathlib import Path

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
