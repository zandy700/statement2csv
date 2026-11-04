# statement2csv

[![CI](https://github.com/zandy700/statement2csv/actions/workflows/ci.yml/badge.svg)](https://github.com/zandy700/statement2csv/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Turn broker statements into clean data for spreadsheets, taxes, and portfolio trackers.

statement2csv reads broker PDF statements and CSV exports and writes:

- a **clean spreadsheet** (CSV or Excel) for Excel, Google Sheets or Numbers,
- a **realized capital gains report** (FIFO, laid out like IRS Form 8949),
- **import files** for [Wealthfolio](https://wealthfolio.app) and
  [Ghostfolio](https://ghostfol.io).

## Why

Many brokers only give you monthly PDF statements, or a CSV in a layout of their own.
You can't sort, filter or sum a PDF, portfolio trackers want their own CSV columns, and
working out what you gained on each sale by hand is tedious. statement2csv reads the
statement once into a normalized list of activities and writes it in the shape you need.

## Privacy

Your statements contain account numbers, names and your whole financial history.
statement2csv runs **fully offline**: it reads the file you give it and writes a CSV
to disk (or stdout). The source (`src/`) imports no network libraries, makes no
network requests, uploads nothing and sends no telemetry. Installing the package
downloads its dependencies, as any `pip` install does; running it does not.

<!-- Demo: add an asciinema recording or GIF here, e.g.
     [![asciicast](https://asciinema.org/a/XXXX.svg)](https://asciinema.org/a/XXXX) -->

## Install

Requires Python 3.11 or newer. The package is not on PyPI yet, so install from a clone.

```sh
git clone https://github.com/zandy700/statement2csv.git
cd statement2csv

# pipx
pipx install .

# or uv
uv tool install .

# or from source, in a virtualenv (also installs the dev tools)
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
```

Excel (`.xlsx`) output needs the optional `xlsx` extra (openpyxl):
`pipx install '.[xlsx]'`, `uv tool install '.[xlsx]'` or `pip install -e '.[xlsx]'`.
CSV output works without it.

## Usage

```sh
# List the available broker parsers
statement2csv brokers

# Detect the broker automatically, write Wealthfolio CSV next to the input
# (statement.wealthfolio.csv)
statement2csv convert statement.pdf

# Pick the broker and target app, choose the output file
statement2csv convert statement.pdf --broker schwab --format ghostfolio -o schwab.csv

# A clean CSV for Excel / Google Sheets / Numbers (statement.spreadsheet.csv)
statement2csv convert statement.pdf -f spreadsheet      # or: -f csv

# ... or a real Excel workbook (needs the xlsx extra)
statement2csv convert statement.pdf -f spreadsheet --xlsx -o activity.xlsx

# Realized capital gains (FIFO). Totals and warnings are printed to stderr.
statement2csv convert activity.csv -f gains -o gains-2024.csv

# Write to stdout (warnings and the summary go to stderr)
statement2csv convert activity.csv -f wealthfolio -o -
```

Options of `convert`:

| Option | Description |
| --- | --- |
| `INPUT` | Broker statement (PDF or CSV export). |
| `--broker`, `-b` | Parser name from `statement2csv brokers`, or `auto` (default) to detect it. |
| `--format`, `-f` | `wealthfolio` (default), `ghostfolio`, `spreadsheet` (alias `csv`) or `gains`. |
| `--output`, `-o` | Output path, or `-` for stdout. Default: the input name with a `.<format>.csv` suffix (`.xlsx` with `--xlsx`). |
| `--xlsx` | Write an Excel workbook instead of CSV. Only for `spreadsheet` and `gains`; needs the `xlsx` extra. |

Rows that cannot be converted are skipped, and a warning for each one is printed to
stderr. Read them: they tell you what is missing from the CSV. The command exits with
code 1, and writes no file, if the broker cannot be detected, the file cannot be parsed
or it contains no activities. `statement2csv --version` prints the version.

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

## Supported outputs

| `--format` | For | Columns | XLSX | Notes |
| --- | --- | --- | --- | --- |
| `spreadsheet` (alias `csv`) | Excel, Google Sheets, Numbers, pandas | `date, broker, account, type, symbol, description, quantity, price, amount, fees, currency` | yes | Every activity, one row each. `amount` is signed (negative = money out) and sell quantities are negative, so a column sum gives net cash flow / net shares bought. |
| `gains` | Taxes (Form 8949 / Schedule D prep) | `description, date_acquired, date_sold, proceeds, cost_basis, gain_loss, term` | yes | Realized gains with FIFO lot matching. Prints short- and long-term totals. **Not tax advice**, see below. |
| `wealthfolio` | [Wealthfolio](https://wealthfolio.app) import | canonical Wealthfolio names | no | The import wizard maps every column automatically. |
| `ghostfolio` | [Ghostfolio](https://ghostfol.io) import | Ghostfolio sample header | no | Ghostfolio has no deposit, withdrawal or split activities, so those rows are skipped. Tax rows are written as `fee`. |

What each file contains, and why, is documented in [docs/formats.md](docs/formats.md).
For the import formats, always review the import preview in the target app before
confirming.

### Spreadsheet example

```csv
date,broker,account,type,symbol,description,quantity,price,amount,fees,currency
2024-01-10,Robinhood,,Buy,AAPL,Apple,40,185.5,-7420,0,USD
2024-02-15,Robinhood,,Dividend,AAPL,Cash Div: ...,,,9.6,0,USD
2024-02-20,Robinhood,,Sell,AAPL,Apple,-30,182.31,5469.18,0.12,USD
```

With `--xlsx`, numbers and dates are real Excel numbers and dates, the header row is
frozen and filters are on.

### Capital gains report

```sh
$ statement2csv convert activity.csv -f gains -o gains.csv
Robinhood: wrote 2 sale lots to gains.csv (Realized gains (FIFO) format)
Realized gains (FIFO):
  Short-term: proceeds      13,972.97  cost basis      13,334.40  gain/loss         638.57 USD
  Long-term:  proceeds           0.00  cost basis           0.00  gain/loss           0.00 USD
  Total:      gain/loss 638.57 USD
Not tax advice. ...
```

```csv
description,date_acquired,date_sold,proceeds,cost_basis,gain_loss,term
30 sh. AAPL,2024-01-10,2024-02-20,5469.18,5565.00,-95.82,short
20 sh. MSFT,2024-01-12,2024-03-22,8503.79,7769.40,734.39,short
```

How it is computed:

- Each sell is matched to the oldest open buys of the same symbol (same account and
  currency) first: **FIFO**. A sale that closes several lots, or part of one, gets one
  row per lot.
- Buy commissions are added to the cost basis; sell commissions are subtracted from the
  proceeds.
- **Long-term** means held more than one year (sold after the one-year anniversary of
  the purchase), otherwise **short-term**.
- Splits in the converted statements rescale open lots.
- `convert` reads one file, so only buys in that file are known. A sale of shares bought
  before the period the file covers gets a row with a blank cost basis and term
  `unknown`, a warning is printed, and its proceeds are left out of the totals. Take
  the basis for those rows from your 1099-B. A broker export that covers your whole
  history (e.g. a full Robinhood activity CSV) avoids this.

> [!WARNING]
> **This is not tax advice.** The gains report is an estimate from the statements you
> give it. It does not apply wash-sale rules, specific-lot or average-cost elections,
> corporate actions other than splits, or adjustments your broker makes. **Your broker's
> Form 1099-B is authoritative.** Use it, or a tax professional, to file.

## Limitations

- The parsers were written against publicly known statement layouts and tested with
  **synthetic** statements (`tests/fixtures/`), not real ones. Real statements may
  differ, so check your first conversion against the original.
- Option trades, reversals and unknown transaction types are skipped with a warning.
- Each statement is treated as a single account. The parsers do not read account
  numbers and the output has no `account` column, so convert one account per file.
- Schwab's older split layout ("Transaction Detail - Purchases & Sales", ...) is not
  supported.
- Robinhood splits are converted only when the description states a ratio
  (for example "2 for 1"); otherwise they are skipped.
- Amounts are assumed to be in USD; all three parsers write `USD`.
- Only the broker's reported activity is converted; there is no portfolio
  reconciliation.
- `convert` reads one file at a time, so the gains report only sees buys in that file.
  Sales of shares bought earlier have no cost basis (see
  [Capital gains report](#capital-gains-report)).
- If a statement fails or converts wrongly, please
  [open an issue](https://github.com/zandy700/statement2csv/issues/new/choose) with a **redacted**
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
