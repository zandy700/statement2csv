# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `spreadsheet` output format (alias `csv`): a clean, human-friendly CSV for Excel,
  Google Sheets and Numbers with columns `date, broker, account, type, symbol,
  description, quantity, price, amount, fees, currency`. Every activity type is kept;
  `amount` and sell quantities are signed.
- `gains` output format: a realized capital gains report with FIFO lot matching, in
  Form 8949-style columns (`description, date_acquired, date_sold, proceeds,
  cost_basis, gain_loss, term`). Handles partial lots, fees in basis and proceeds,
  short- vs long-term holding periods, splits, and warns about sales without enough
  earlier buys. Prints short-/long-term totals and a not-tax-advice disclaimer (the
  broker's 1099-B is authoritative).
- `--xlsx` option for `spreadsheet` and `gains`: writes an Excel workbook with real
  number and date cells. Needs the new optional `xlsx` extra (openpyxl).

### Changed

- Positioning: statement2csv turns broker statements into clean data for spreadsheets,
  taxes and portfolio trackers, not only Wealthfolio / Ghostfolio imports.
- Exporters build a table that is written as CSV or XLSX. `ExportResult` has
  `warnings` and `summary` lines, shown by the CLI.

### Fixed

- `--broker AUTO` (any case) now auto-detects instead of failing as an unknown broker.
- Schwab: a date printed with a year (`MM/DD/YYYY`) keeps that year instead of being
  re-guessed from the statement period.
- Schwab: a transaction line with an unreadable date now produces a warning. It used to
  end the table silently, dropping it and every later row on the page.
- Robinhood: cash rows with a `$0.00` amount and trades with a zero quantity are skipped
  with a warning, as the PDF parsers do, instead of producing zero-value activities.
- Ghostfolio: a dividend whose amount differs from quantity × unit price (e.g. net of
  withholding) is exported as Quantity 1 × amount, so it matches the Wealthfolio export.
- `docs/formats.md`: the Ghostfolio fee example now matches the actual output.

## [0.1.0] - 2026-11-03

### Added

- `statement2csv convert` command with `--broker` (name or `auto` detection),
  `--format` (`wealthfolio` or `ghostfolio`) and `--output` (path or `-` for stdout).
- `statement2csv brokers` command listing the available parsers.
- Parsers for Fidelity (PDF), Charles Schwab (PDF) and Robinhood (CSV), tested against
  synthetic fixtures.
- Wealthfolio and Ghostfolio CSV exporters. Rows a target cannot represent are skipped
  with a warning.
- Plugin-style broker registry: a new parser is one module in `statement2csv/parsers/`.
- Documentation of the target import formats in `docs/formats.md`.
- Everything runs offline; no network access is used.

[Unreleased]: https://github.com/OWNER/REPO/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/OWNER/REPO/releases/tag/v0.1.0
