# statement2csv

Convert broker PDF statements (and broker CSV exports) into CSV files you can import
into [Wealthfolio](https://wealthfolio.app) and [Ghostfolio](https://ghostfol.io).
Runs fully offline.

```sh
uv venv && uv pip install -e '.[dev]'
statement2csv brokers
statement2csv convert statement.pdf --broker auto --format wealthfolio -o out.csv
```

## Supported brokers

| Broker | Input | Notes |
| --- | --- | --- |
| `fidelity` | Monthly "INVESTMENT REPORT" PDF, Activity section | Core money-market sweep rows are ignored |
| `schwab` | Brokerage statement PDF, "Transaction Details" table | Older split "Transaction Detail - ..." layout not supported |
| `robinhood` | "Account activity" CSV export | Options, journals and ACATS rows are skipped |

The PDF parsers are based on publicly known statement layouts and tested against
synthetic statements (`tests/fixtures/generate_*.py`). Check the output of your first
conversion carefully. Rows that can't be converted (option trades, reversals, unknown
transaction types, ...) are skipped with a warning, so read the warnings.

Ghostfolio has no deposit, withdrawal or split activities; those rows are skipped when
exporting to Ghostfolio. See [docs/formats.md](docs/formats.md) for the target formats.

## Adding a broker

Add one module to `src/statement2csv/parsers/` with a `BrokerParser` subclass. It is
discovered automatically. Shared helpers live in `parsers/_common.py`.
