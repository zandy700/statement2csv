# Contributing

Thanks for helping. The most useful contributions are new broker parsers and fixes
for statement layouts that do not convert correctly.

## Never commit real financial data

**Do not commit, attach or paste real statements, broker CSV exports, account numbers,
names, addresses or real balances** in commits, issues, pull requests or tests. This
applies to git history too: a file removed in a later commit is still public.

`.gitignore` blocks `*.pdf` and `*.csv` everywhere except under `tests/fixtures/`, but
that is only a safety net. Fixtures must be **synthetic**: invented holder, invented
account number, invented amounts.

### Redacting samples

When reporting a problem or requesting a broker, share only the structure:

- Replace names, addresses, account and routing numbers with fake values.
- Change the amounts, quantities and dates. Keep the formatting (decimal separators,
  parentheses for negatives, date format, column order) because that is what matters.
- Keep only the few rows and headers that show the problem.
- Check PDF text copied into an issue for hidden extras such as barcodes, footers and
  customer IDs.
- Do not upload a PDF "with the sensitive parts blacked out". Black boxes drawn on top
  of a PDF usually leave the text underneath. Copy the text and redact that instead.

## Development setup

Python 3.11 or newer.

```sh
git clone https://github.com/zandy700/statement2csv.git
cd statement2csv
uv venv && uv pip install -e '.[dev]'
```

Without uv: `python -m venv .venv && .venv/bin/pip install -e '.[dev]'`. The `dev` extra installs pytest,
ruff and reportlab, which the PDF fixture generators use.

## Tests and linting

```sh
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .   # use `ruff format .` to fix formatting
```

CI runs the same three commands on Python 3.11, 3.12 and 3.13.

## Adding a broker

1. **Parser.** Create `src/statement2csv/parsers/<broker>.py` with a concrete
   subclass of `BrokerParser` (see `parsers/base.py`):

   ```python
   class MyBrokerParser(BrokerParser):
       name = "mybroker"  # lowercase, no spaces, not "auto"
       display_name = "My Broker"
       file_types = (".pdf",)  # or (".csv",)

       def detect(self, path: Path) -> bool: ...
       def parse(self, path: Path) -> list[Activity]: ...
   ```

   Subclasses register themselves and the package imports every module that does not
   start with `_`, so nothing else needs editing. `detect` must be fast, must not
   raise for other brokers' files and must stay offline. `parse` raises `ParserError`
   for input that is not this broker's statement. For a row you cannot convert, call
   `warnings.warn(...)` naming the row and skip it; the CLI shows these warnings.
   Document the layout and the mapping at the top of the module, as the existing
   parsers do. Shared helpers (money and date parsing, PDF text extraction, trade
   building) are in `parsers/_common.py`.

2. **Model conventions.** Build `Activity` objects from `models.py`: amounts and
   quantities are non-negative `Decimal`s, direction comes from the activity type,
   and `amount` is the broker's final cash total including fees. Read the module
   docstring there before writing the parser.

3. **Fixture.** Add a synthetic statement under `tests/fixtures/`. For a PDF, write
   a generator, `tests/fixtures/generate_<broker>.py`, using reportlab. The existing
   `generate_fidelity.py` and `generate_schwab.py` are good models. Run it with
   `.venv/bin/python tests/fixtures/generate_<broker>.py` and commit both the script
   and the PDF. Create the canvas with `invariant=1` so the output is deterministic
   and regenerating gives a byte-identical file. For a CSV export, a small hand-written file such as
   `robinhood_activity.csv` is enough. Make it cover buys, sells, dividends, interest,
   fees, deposits and rows you intend to skip.

4. **Fixture path.** Add a pytest fixture for it in `tests/conftest.py`, as for the
   existing brokers (`fidelity_pdf`-style fixtures pointing into `tests/fixtures/`).

5. **Tests.** Add `tests/test_parser_<broker>.py`: assert the exact activities parsed
   from the fixture, that `detect` accepts it and rejects other brokers' fixtures, and
   that unsupported rows produce warnings. Then update the shared test modules:

   - `tests/test_detection.py`: add the fixture to `FIXTURE_FILES` and the parser to
     `PARSERS`, so the detect matrix proves the new parser accepts only its own file
     and the others do not accept it.
   - `tests/test_cli_e2e.py`: add the fixture to `FIXTURE_FILES`, and its activity
     count and number of deposits, withdrawals and splits to `TOTALS` and
     `CASH_MOVEMENTS`. The parametrized tests then run it through both exporters.

6. **Docs.** Add the broker to the table in `README.md` and to the changelog under
   "Unreleased".

7. Run the tests and linters, then open a pull request using the template.

## Conventions

- Quantities, prices, fees and amounts are non-negative `Decimal`s. The activity type
  gives the direction. Never use floats for money.
- `amount` is the final cash total of the activity, fees and taxes included.
- Warn and skip rather than guess. If a row is ambiguous (unknown transaction type,
  options, reversals), call `warnings.warn(...)` naming the row and leave it out.
- `detect()` must never raise and must not match other brokers' files. Check for
  text that is specific to the broker, not for generic words like "Statement".
- Keep parsers offline: no network access, no telemetry.
- Code is formatted with `ruff format`, line length 100.

## Pull requests

Keep them focused. Describe what changed and which statement layout you based it on.
