"""Command-line interface."""

from __future__ import annotations

import sys
import warnings
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from statement2csv import __version__
from statement2csv.exporters import ALIASES, EXPORTERS, get_exporter
from statement2csv.parsers import ParserError, all_parsers, detect_parser, get_parser

HELP = (
    "Turn broker statements into clean data for spreadsheets, taxes and portfolio trackers "
    "(Wealthfolio, Ghostfolio). Fully offline."
)

app = typer.Typer(
    help=HELP,
    no_args_is_help=True,
    add_completion=False,
)

OutputFormat = StrEnum("OutputFormat", {name: name for name in [*EXPORTERS, *ALIASES]})
DEFAULT_FORMAT = OutputFormat("wealthfolio")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"statement2csv {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """Turn broker statements into clean data for spreadsheets, taxes and portfolio trackers."""


@app.command()
def convert(
    input_path: Annotated[
        Path,
        typer.Argument(
            metavar="INPUT",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Broker statement (PDF or CSV export).",
        ),
    ],
    broker: Annotated[
        str, typer.Option("--broker", "-b", help="Broker parser name, or 'auto' to detect.")
    ] = "auto",
    output_format: Annotated[
        OutputFormat,
        typer.Option(
            "--format",
            "-f",
            help="Output format: an app's import CSV, a spreadsheet, or a gains report.",
        ),
    ] = DEFAULT_FORMAT,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            dir_okay=False,
            help="Output path ('-' for stdout). Default: INPUT with a .<format>.csv suffix.",
        ),
    ] = None,
    xlsx: Annotated[
        bool,
        typer.Option(
            "--xlsx",
            help="Write an Excel workbook instead of CSV (spreadsheet and gains formats; "
            "needs the 'xlsx' extra).",
        ),
    ] = False,
) -> None:
    """Convert INPUT into a CSV (or XLSX) file."""
    exporter = get_exporter(output_format.value)
    if xlsx and not exporter.supports_xlsx:
        xlsx_formats = ", ".join(n for n, cls in EXPORTERS.items() if cls.supports_xlsx)
        _fail(f"--xlsx works only with --format {xlsx_formats}; {exporter.name} is CSV only")
    if xlsx and output is not None and str(output) == "-":
        _fail("--xlsx cannot write to stdout; give an output file with -o")

    try:
        auto = broker.strip().lower() == "auto"
        parser = detect_parser(input_path) if auto else get_parser(broker.strip())
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            activities = parser.parse(input_path)
    except ParserError as exc:
        _fail(str(exc))
    for warning in caught:
        typer.secho(f"Warning: {warning.message}", fg=typer.colors.YELLOW, err=True)
    if not activities:
        _fail(f"no activities found in {input_path.name}; nothing written")

    exporter.broker = parser.display_name
    if output is None:
        suffix = "xlsx" if xlsx else "csv"
        output = input_path.with_name(f"{input_path.stem}.{exporter.name}.{suffix}")

    to_stdout = str(output) == "-"
    try:
        if xlsx:
            result = exporter.export_xlsx(activities, output)
        elif to_stdout:
            result = exporter.export(activities, sys.stdout)
        else:
            with output.open("w", encoding="utf-8", newline="") as fh:
                result = exporter.export(activities, fh)
    except ImportError as exc:
        _fail(str(exc))
    except OSError as exc:
        _fail(f"cannot write {output}: {exc.strerror or exc}")

    for skipped in result.skipped:
        a = skipped.activity
        what = " ".join(str(x) for x in (a.date, a.activity_type, a.symbol, a.amount) if x)
        typer.secho(f"Skipped {what}: {skipped.reason}", fg=typer.colors.YELLOW, err=True)
    for message in result.warnings:
        typer.secho(f"Warning: {message}", fg=typer.colors.YELLOW, err=True)
    typer.echo(
        f"{parser.display_name}: wrote {result.written} {exporter.row_noun} to "
        f"{'stdout' if to_stdout else output} ({exporter.display_name} format)"
        + (f", skipped {len(result.skipped)}" if result.skipped else ""),
        err=True,
    )
    for line in result.summary:
        typer.echo(line, err=True)
    if result.written == 0:
        why = "every activity was skipped" if result.skipped else f"no {exporter.row_noun}"
        typer.secho(
            f"Warning: {why}; {output} only has a header row",
            fg=typer.colors.YELLOW,
            err=True,
        )


def _fail(message: str) -> NoReturn:
    typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


@app.command()
def brokers() -> None:
    """List the available broker parsers."""
    parsers = all_parsers()
    if not parsers:
        typer.echo("No broker parsers installed yet.")
        return
    width = max(len(name) for name in parsers)
    for name, cls in parsers.items():
        types = ", ".join(cls.file_types)
        typer.echo(f"{name:<{width}}  {cls.display_name} ({types})")


if __name__ == "__main__":  # pragma: no cover
    app()
