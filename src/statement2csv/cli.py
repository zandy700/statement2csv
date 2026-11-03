"""Command-line interface."""

from __future__ import annotations

import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

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
        activities = parser.parse(input_path)
    except ParserError as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    exporter = get_exporter(output_format.value)
    if output is None:
        output = input_path.with_name(f"{input_path.stem}.{exporter.name}.csv")

    if str(output) == "-":
        result = exporter.export(activities, sys.stdout)
    else:
        with output.open("w", encoding="utf-8", newline="") as fh:
            result = exporter.export(activities, fh)

    for skipped in result.skipped:
        a = skipped.activity
        what = " ".join(str(x) for x in (a.date, a.activity_type, a.symbol, a.amount) if x)
        typer.secho(
            f"Skipped {what}: {skipped.reason}",
            fg=typer.colors.YELLOW,
            err=True,
        )
    destination = "stdout" if str(output) == "-" else str(output)
    typer.echo(
        f"{parser.display_name}: wrote {result.written} activities to {destination} "
        f"({exporter.display_name} format)"
        + (f", skipped {len(result.skipped)}" if result.skipped else ""),
        err=True,
    )


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
