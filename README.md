# statement2csv

[![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Convert broker PDF statements and CSV exports into CSV files you can import into
[Wealthfolio](https://wealthfolio.app) and [Ghostfolio](https://ghostfol.io).

## Why

Many brokers only give you monthly PDF statements, or a CSV in a layout of their own.
Wealthfolio and Ghostfolio import CSV files with a specific set of columns, so those
statements cannot be imported as they are. Users asked for exactly this in the
Wealthfolio Show HN thread. statement2csv reads the statement and writes a CSV in the
format the target app expects.

## Privacy

Your statements contain account numbers, names and your whole financial history.
statement2csv runs **fully offline**: it reads the file you give it and writes a CSV
to disk (or stdout). It does not make network requests, upload anything or send
telemetry.

<!-- Demo: add an asciinema recording or GIF here, e.g.
     [![asciicast](https://asciinema.org/a/XXXX.svg)](https://asciinema.org/a/XXXX) -->

## Install

Requires Python 3.11 or newer. The package is not on PyPI yet, so install from a clone.

```sh
git clone https://github.com/OWNER/REPO.git
cd REPO

# pipx
pipx install .

# or uv
uv tool install .

# or from source, in a virtualenv (also installs the dev tools)
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
```

## Usage

```sh
# List the available broker parsers
statement2csv brokers

# Detect the broker automatically, write Wealthfolio CSV next to the input
# (statement.wealthfolio.csv)
statement2csv convert statement.pdf

# Pick the broker and target app, choose the output file
statement2csv convert statement.pdf --broker schwab --format ghostfolio -o schwab.csv

# Write to stdout (warnings and the summary go to stderr)
statement2csv convert activity.csv -f wealthfolio -o -
```

Options of `convert`:

| Option | Description |
| --- | --- |
| `INPUT` | Broker statement (PDF or CSV export). |
| `--broker`, `-b` | Parser name from `statement2csv brokers`, or `auto` (default) to detect it. |
| `--format`, `-f` | `wealthfolio` (default) or `ghostfolio`. |
| `--output`, `-o` | Output path, or `-` for stdout. Default: the input name with a `.<format>.csv` suffix. |

Rows that cannot be converted are skipped, and a warning for each one is printed to
stderr. Read them: they tell you what is missing from the CSV.

## Supported brokers

| Broker | `--broker` | Input | Status |
| --- | --- | --- | --- |
| Fidelity | `fidelity` | Monthly "Investment Report" PDF, Activity section | Tested on synthetic statements only |
| Charles Schwab | `schwab` | Brokerage statement PDF, "Transaction Details" table | Tested on synthetic statements only |
| Robinhood | `robinhood` | "Account activity" CSV export | Tested on a synthetic export only |

Known gaps: Fidelity's core money-market sweep rows are ignored. Schwab's older split
"Transaction Detail - ..." layout is not supported. Robinhood options, journals and
ACATS rows are skipped. Details are in the docstring at the top of each parser in
`src/statement2csv/parsers/`.

## Output formats

| Format | Notes |
| --- | --- |
| `wealthfolio` | Canonical Wealthfolio column names, so the import wizard maps them automatically. |
| `ghostfolio` | Ghostfolio has no deposit, withdrawal or split activities, so those rows are skipped. Tax rows are written as `fee`. |

What each file contains, and why, is documented in [docs/formats.md](docs/formats.md).
Always review the import preview in the target app before confirming.

## Limitations

- The parsers were written against publicly known statement layouts and tested with
  **synthetic** statements (`tests/fixtures/`), not real ones. Real statements may
  differ, so check your first conversion against the original.
- Option trades, reversals and unknown transaction types are skipped with a warning.
- Only the broker's reported activity is converted; there is no portfolio
  reconciliation.
- If a statement fails or converts wrongly, please
  [open an issue](https://github.com/OWNER/REPO/issues/new/choose) with a **redacted**
  sample. Remove names, addresses and account numbers, and change the amounts.
  Never post a real statement. See [CONTRIBUTING.md](CONTRIBUTING.md#redacting-samples).

## Add a broker

1. Add `src/statement2csv/parsers/<broker>.py` with a `BrokerParser` subclass that sets
   `name` and `display_name` and implements `detect(path)` and `parse(path)`.
   It is discovered automatically; no other file needs editing.
2. Add a synthetic fixture (and a generator script for PDFs) in `tests/fixtures/`.
3. Add tests in `tests/test_parser_<broker>.py`.

The full walkthrough is in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
