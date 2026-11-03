# statement2csv

Convert broker PDF statements (and broker CSV exports) into CSV files you can import
into [Wealthfolio](https://wealthfolio.app) and [Ghostfolio](https://ghostfol.io).
Runs fully offline.

```sh
uv venv && uv pip install -e '.[dev]'
statement2csv brokers
statement2csv convert statement.pdf --broker auto --format wealthfolio -o out.csv
```

See [docs/formats.md](docs/formats.md) for the target CSV formats.
