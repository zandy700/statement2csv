"""Command-line interface."""

from __future__ import annotations

import sys
import warnings
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from statement2csv import __version__
from statement2csv.exporters import EXPORTERS, get_exporter
from statement2csv.parsers import ParserError, all_parsers, detect_parser, get_parser

app = typer.Typer(
    help="Convert broker statements into Wealthfolio / Ghostfolio import CSVs (offline).",
    no_args_is_help=True,
    add_completion=False,
)

OutputFormat = StrEnum("OutputFormat", {name: name for name in EXPORTERS})
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
    """Convert broker statements into Wealthfolio / Ghostfolio import CSVs (offline)."""


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
        OutputFormat, typer.Option("--format", "-f", help="Target application.")
    ] = DEFAULT_FORMAT,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            dir_okay=False,
            help="Output CSV path ('-' for stdout). Default: INPUT with a .<format>.csv suffix.",
        ),
    ] = None,
) -> None:
    """Convert INPUT into an importable CSV."""
    try:
        parser = detect_parser(input_path) if broker == "auto" else get_parser(broker)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            activities = parser.parse(input_path)
    except ParserError as exc:
        _fail(str(exc))
    for warning in caught:
        typer.secho(f"Warning: {warning.message}", fg=typer.colors.YELLOW, err=True)
    if not activities:
        _fail(f"no activities found in {input_path.name}; nothing written")

    exporter = get_exporter(output_format.value)
    if output is None:
        output = input_path.with_name(f"{input_path.stem}.{exporter.name}.csv")

    to_stdout = str(output) == "-"
    try:
        if to_stdout:
            result = exporter.export(activities, sys.stdout)
        else:
            with output.open("w", encoding="utf-8", newline="") as fh:
                result = exporter.export(activities, fh)
    except OSError as exc:
        _fail(f"cannot write {output}: {exc.strerror or exc}")

    for skipped in result.skipped:
        a = skipped.activity
        what = " ".join(str(x) for x in (a.date, a.activity_type, a.symbol, a.amount) if x)
        typer.secho(f"Skipped {what}: {skipped.reason}", fg=typer.colors.YELLOW, err=True)
    typer.echo(
        f"{parser.display_name}: wrote {result.written} activities to "
        f"{'stdout' if to_stdout else output} ({exporter.display_name} format)"
        + (f", skipped {len(result.skipped)}" if result.skipped else ""),
        err=True,
    )
    if result.written == 0:
        typer.secho(
            f"Warning: every activity was skipped; {output} only has a header row",
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
