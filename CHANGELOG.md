# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
