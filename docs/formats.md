# Output formats

This document records what statement2csv writes for each output format, and why.

- [Spreadsheet](#spreadsheet) (`spreadsheet`, alias `csv`): our own universal layout.
- [Gains](#gains) (`gains`): realized capital gains, Form 8949-style.
- [Wealthfolio](#wealthfolio) and [Ghostfolio](#ghostfolio): the apps' import formats.

The import formats were researched on **2026-11-03** from the source code and docs of
both projects.

| App         | Version checked                          | Commit                                     |
| ----------- | ---------------------------------------- | ------------------------------------------ |
| Wealthfolio | v3.12.0 (released 2026-11-01)            | `367615abd9db92a046b9d1fb65eb2c1ae33d8b47` |
| Ghostfolio  | 3.97.0 (released 2026-11-02)             | `fb8b12aa7eb2a9f28dc92ec18d7c951743782746` |

Both apps change their importers often. When upgrading, re-check the sources listed
at the end of each section.

---

## Spreadsheet

`--format spreadsheet` (or `csv`). A layout of our own, for people rather than an
importer: Excel, Google Sheets, Numbers, LibreOffice, pandas. With `--xlsx` the same
table is written as an Excel workbook (needs the `xlsx` extra).

| Column        | Contents |
| ------------- | -------- |
| `date`        | ISO `YYYY-MM-DD` (a real date cell in XLSX). Rows are sorted by date; same-day rows keep the statement order. |
| `broker`      | Display name of the parser, e.g. `Charles Schwab`. |
| `account`     | Account name if the parser provides one, else blank. Always present so the columns don't move. |
| `type`        | `Buy`, `Sell`, `Dividend`, `Interest`, `Fee`, `Tax`, `Deposit`, `Withdrawal`, `Split`. |
| `symbol`      | Ticker or CUSIP, blank for pure cash rows. |
| `description` | The broker's description. If there is none: `N-for-1 split` for splits, `Q shares x P` for per-share dividends. |
| `quantity`    | **Signed** change in shares: positive for buys, negative for sells. Blank on every other type. |
| `price`       | Price per share for buys and sells, blank otherwise. |
| `amount`      | **Signed** cash effect, fees included: negative for buys (total paid), withdrawals, fees and taxes; positive for sells (net proceeds), deposits, dividends and interest. The broker's own total is used when the statement has one, else quantity × price ± fee. Blank for splits (the ratio is not cash). |
| `fees`        | Commission/fees of the activity, already included in `amount` (do not subtract them again). On `Fee` rows it is the fee itself, so the column totals all fees paid. |
| `currency`    | ISO 4217 code. |

Why signed: in a spreadsheet the useful operations are `SUM(amount)` (net cash flow) and
a pivot of `SUM(quantity)` by symbol (net shares bought; splits are not applied). The
import formats keep everything positive because the apps want that; this one does not
feed an importer.

Numbers are written in plain notation (`1859.95`, no thousands separators, no currency
symbol) so every spreadsheet locale parses them. XLSX cells use the `#,##0.00` format for
`amount` and `fees`; the header row is frozen and has filters.

```csv
date,broker,account,type,symbol,description,quantity,price,amount,fees,currency
2024-02-02,Fidelity,,Buy,AAPL,You Bought: APPLE INC,10.5,185.2,-1949.55,4.95,USD
2024-02-09,Fidelity,,Sell,MSFT,You Sold: MICROSOFT CORP,-8.25,375.4,3096.98,0.07,USD
2024-02-16,Fidelity,,Tax,NVS,Foreign Tax Paid: NOVARTIS AG SPON ADR,,,-13.23,0,USD
2024-02-27,Fidelity,,Fee,,Wire Transfer Fee,,,-15,15,USD
```

---

## Gains

`--format gains`. Realized capital gains, one row per sold lot, with columns that
follow IRS Form 8949 (columns a, b, c, d, e, h, plus the Part I / Part II split as
`term`). With `--xlsx` the totals and the disclaimer go to a second `Summary` sheet.

> **Not tax advice.** This is an estimate from the statement you convert. It does not
> apply wash-sale rules (Form 8949 column g), and it can't know about lots, corporate
> actions or basis adjustments that are not in the file. **Your broker's Form 1099-B is
> authoritative.**

| Column          | Form 8949 | Contents |
| --------------- | --------- | -------- |
| `description`   | (a) | `<quantity> sh. <symbol>`, e.g. `10 sh. AAPL`. |
| `date_acquired` | (b) | Buy date of the lot. Blank if no earlier buy was found. |
| `date_sold`     | (c) | Sell date. |
| `proceeds`      | (d) | Net proceeds (commission subtracted), in cents. |
| `cost_basis`    | (e) | Cost including the buy commission, in cents. Blank if unknown. |
| `gain_loss`     | (h) | `proceeds - cost_basis`. Negative for a loss. Blank if the basis is unknown. |
| `term`          | Part I / II | `short`, `long`, or `unknown` (no basis). |
| `account`       |     | Only when at least one activity has an account. |

### Lot matching

1. Only BUY, SELL and SPLIT activities with a symbol are used; everything else is
   ignored (not reported as skipped). They are processed in date order. On the same
   date, splits come first, then buys, then sells, so a day trade matches whatever
   order the statement lists it in. Older lots still go first (FIFO).
2. A BUY opens a lot. Basis = the broker's total paid (`amount`) if the statement has
   it, else quantity × price + fee.
3. A SELL closes the oldest open lots of the same **account, symbol and currency**
   first. Net proceeds = `amount`, else quantity × price - fee. When a sale closes
   several lots, or part of one, proceeds are split between the rows by quantity, and a
   partial lot's basis is split the same way. Each piece is rounded to cents and the
   last piece gets the remainder, so the rows of one sale add up to its proceeds and the
   rows of one lot add up to its basis exactly.
4. A SPLIT multiplies the quantity of every open lot of that symbol (in that account) by
   the ratio. Basis and acquisition date stay the same.
5. **Holding period.** Long-term if held *more than one year*: the sell date is after
   the one-year anniversary of the buy date (bought 2023-01-15: sold 2024-01-15 is
   short-term, 2024-01-16 is long-term). A lot bought on Feb 29 has its anniversary on
   Feb 28.
6. **Not enough buys.** If a sale needs more shares than the open lots hold, the matched
   part is reported normally and the rest gets a row with blank `date_acquired`,
   `cost_basis` and `gain_loss` and term `unknown`. A warning names the sale. This is
   what happens for shares bought before the period of a monthly statement.

### Summary

Printed to stderr (and written to the `Summary` sheet in XLSX), per currency:

```
Realized gains (FIFO):
  Short-term: proceeds         760.38  cost basis         742.69  gain/loss          17.69 USD
  Long-term:  proceeds           0.00  cost basis           0.00  gain/loss           0.00 USD
  Total:      gain/loss 17.69 USD
  Not included: 3,096.98 USD of proceeds with unknown cost basis (term 'unknown').
Not tax advice. These figures are an estimate (FIFO, no wash-sale adjustments) from the statement you converted. Your broker's Form 1099-B is authoritative.
```

Totals are sums of the rounded row values, so they match the file.

### Not handled

Wash sales, short sales, options, mergers/spin-offs and other corporate actions apart
from splits, transfers in with a carried-over basis, gifted or inherited shares, and
lot elections other than FIFO (specific identification, average cost for funds). For
those, use the 1099-B.

---

## Wealthfolio

### How the import works

Activities → Import is a wizard: upload a CSV, **map columns**, map activity-type
values, review, confirm. The mapping step auto-matches headers. It first looks for an
exact canonical field name (case-insensitive), then a list of aliases (`type`,
`unit_price`, `price`, `ticker`, `note`, …). If we write the canonical header names,
the default template maps every column without user input.

The parse config defaults to `delimiter: auto`, `dateFormat: auto`,
`decimalSeparator: auto`, `thousandsSeparator: auto` (`default-activity-template.ts`).

### Columns (canonical field names)

From `ImportFormat` in `apps/frontend/src/lib/constants.ts`:

| Field            | Required for mapping\* | Notes |
| ---------------- | ---------------------- | ----- |
| `date`           | yes | ISO `YYYY-MM-DD` preferred. Full ISO-8601 timestamps also accepted. |
| `activityType`   | yes | One of the enum values below. |
| `symbol`         | yes (column) | Ticker, e.g. `AAPL`, `RY.TO`, `IWDA.AS`. Leave blank on cash rows (older `$CASH-USD` style is still accepted). |
| `quantity`       | yes (column) | Positive. Blank on cash rows. Up to 8 decimals. |
| `unitPrice`      | yes (column) | Positive, in activity currency. Blank on cash rows. |
| `amount`         | no (since 3.10) | **Final** cash total, *including* fee and tax. Required on cash/income rows (DEPOSIT, WITHDRAWAL, DIVIDEND, INTEREST, FEE, TAX, CREDIT) and on SPLIT (where it is the ratio). For BUY/SELL, leave blank and Wealthfolio computes `qty × price ± fee/tax`. An explicit `0` is kept as zero. |
| `currency`       | no | ISO 4217. Falls back to asset currency, then account currency. |
| `fee`            | no | Already included in `amount`. Do not deduct it twice. |
| `tax`            | no | Same as `fee`. |
| `comment`        | no | Free text. |
| `account`        | no | Per-row account, matched by name, ID or account number. If missing, rows go to the account picked in the wizard. |
| `isin`           | no | Alternative to `symbol` for asset matching. |
| `instrumentType` | no | e.g. `EQUITY`, `CRYPTO`. Helps classify new symbols. |
| `fxRate`         | no | Activity currency → account currency. |
| `subtype`        | no | e.g. `DRIP`, `QUALIFIED`, `WITHHOLDING`, `COUPON`, `MANAGEMENT_FEE`. |

\* `IMPORT_REQUIRED_FIELDS = [date, activityType, symbol, quantity, unitPrice]`. These
columns must be *mapped* in an investment account import. Individual cash rows may still
leave symbol/quantity/unitPrice empty. Cash-only accounts need only
`date, activityType, amount`.

### Activity types

`BUY, SELL, SPLIT, DIVIDEND, INTEREST, DEPOSIT, WITHDRAWAL, TRANSFER_IN, TRANSFER_OUT,
FEE, TAX, CREDIT, ADJUSTMENT` (plus internal `UNKNOWN`, which is not importable). The
default template maps each value to itself. Matching normalizes case and turns spaces
and dashes into `_`.

Fields each type needs (from `docs/activities/activity-types.md`, "Form Field Requirements"):

| Type        | Required |
| ----------- | -------- |
| BUY / SELL  | symbol, quantity, unitPrice, currency (amount optional, computed) |
| DIVIDEND    | symbol, amount, currency |
| INTEREST    | amount, currency (symbol optional) |
| DEPOSIT / WITHDRAWAL | amount, currency |
| FEE         | amount (or fee), currency |
| TAX         | amount, currency |
| SPLIT       | symbol, amount (= ratio, e.g. `2` for 2-for-1, `3` for 3-for-1) |

### Dates and numbers

- Dates: `auto` detection. ISO `YYYY-MM-DD` is recommended. For ambiguous `DD/MM` vs
  `MM/DD`, the wizard asks the user. Selectable presets include `YYYY-MM-DD`,
  `DD/MM/YYYY`, `MM/DD/YYYY`, `DD.MM.YYYY`, `DD-MM-YYYY`, datetime variants and
  `ISO8601`.
- Numbers: decimal and thousands separators are auto-detected. Currency symbols,
  thousands separators, negatives and parenthesised negatives are tolerated. Plain
  `1234.56` is the safe choice.
- Signs: quantities and amounts are positive. The activity type gives the direction.

### What statement2csv writes

```csv
date,symbol,quantity,activityType,unitPrice,currency,fee,amount,comment
2024-01-15,AAPL,10,BUY,185.5,USD,4.95,,Initial purchase
2024-02-01,AAPL,,DIVIDEND,,USD,0,2.4,Q4 dividend
2024-03-01,,,DEPOSIT,,USD,0,5000,
2024-05-15,NVDA,,SPLIT,,USD,0,3,3-for-1 split
2024-06-01,AAPL,,TAX,,USD,0,0.36,Withholding
```

- `account` is added as the last column only when at least one activity has an account.
- BUY/SELL `amount` is left blank unless the parser has the broker's own final total.
  In that case it is written as-is, because Wealthfolio expects a total that already
  includes fees.
- `tax`, `fxRate`, `subtype`, `instrumentType` and `isin` are not written yet. They are
  optional and the Activity model does not carry them.

Upstream example from the guide (native format):

```csv
date,symbol,instrumentType,quantity,activityType,unitPrice,currency,fee,tax,amount,fxRate,subtype
2025-03-03,VTI,EQUITY,4,BUY,250.00,USD,1.00,0,1001.00,,
2025-03-10,VTI,EQUITY,,DIVIDEND,,USD,0,2.50,18.50,,
2025-03-15,,,,DEPOSIT,,USD,0,0,500.00,,
```

### Uncertainties

- The guide's column order is `date,symbol,instrumentType,quantity,activityType,…`.
  The bundled `public/sample-import.csv` uses `date,type,symbol,instrumentType,quantity,unit_price,…`.
  Both auto-map (`type` and `unit_price` are aliases), so order and alias choice should not
  matter. We use the canonical names.
- The bundled sample has a DIVIDEND row with `quantity`/`unit_price` and no `amount`.
  The docs say income rows *require* `amount`. We always write `amount` for income.
- Releases **before 3.10** also required an `amount` column on BUY/SELL. Users on old
  versions may need to fill it in.

### Sources

- Docs, CSV import guide: https://wealthfolio.app/docs/guide/csv-import/
- Docs, activities: https://wealthfolio.app/docs/guide/activities/
- Activity type reference: https://github.com/wealthfolio/wealthfolio/blob/main/docs/activities/activity-types.md
- Field enum, required fields, activity types: https://github.com/wealthfolio/wealthfolio/blob/main/apps/frontend/src/lib/constants.ts
- Header auto-mapping aliases: https://github.com/wealthfolio/wealthfolio/blob/main/apps/frontend/src/pages/activity/import/hooks/use-import-mapping.ts
- Date format presets: https://github.com/wealthfolio/wealthfolio/blob/main/apps/frontend/src/pages/activity/import/utils/date-format-options.ts
- Default parse config: https://github.com/wealthfolio/wealthfolio/blob/main/apps/frontend/src/pages/activity/import/utils/default-activity-template.ts
- Bundled sample: https://github.com/wealthfolio/wealthfolio/blob/main/apps/frontend/public/sample-import.csv

(The repo moved from `afadil/wealthfolio` to `wealthfolio/wealthfolio`. The old URL redirects.)

---

## Ghostfolio

### How the import works

Portfolio → Activities → Import accepts CSV or JSON. The **browser** parses the CSV
(`ImportActivitiesService.importCsv`, papaparse with `header: true, dynamicTyping: true`)
into JSON activities, then POSTs them to `/api/v1/import`. There is no mapping UI. Each
field is looked up by a fixed list of **case-insensitive header names**, and the first
one present wins:

| Field       | Accepted headers (case-insensitive) | Required |
| ----------- | ----------------------------------- | -------- |
| account     | `account`, `accountid` | no. Matched against the user's account **id** or **name** (case-insensitive). If nothing matches, no account is set. |
| comment     | `comment`, `note` | no |
| currency    | `ccy`, `currency`, `currencyprimary` | **yes**, must be a non-empty string |
| dataSource  | `datasource` | no (see below) |
| date        | `date`, `tradedate` | **yes** |
| fee         | `commission`, `fee`, `ibcommission` | **yes**, must be a number (`0` if none). `abs()` is applied. |
| quantity    | `qty`, `quantity`, `shares`, `units` | **yes**, number, `abs()` applied |
| symbol      | `code`, `symbol`, `ticker` | **yes** |
| type        | `action`, `buy/sell`, `type` | **yes** |
| unitPrice   | `price`, `tradeprice`, `unitprice`, `value` | **yes**, number, `abs()` applied |

Because of `dynamicTyping`, numeric cells must be plain JS-parsable numbers: dot as the
decimal separator, no thousands separator, no currency symbol. An **empty** numeric cell
fails validation (`activities.N.fee is not valid`). Always write `0`.

### Activity types

Type cell values (case-insensitive): `buy`, `sell`, `dividend`, `fee`, `interest`,
`liability`. Anything else fails with `activities.N.type is not valid`.

Prisma enum `Type { BUY DIVIDEND FEE INTEREST LIABILITY SELL }`. There is **no**
deposit, withdrawal, split or tax type. Cash is tracked as an account balance. Splits
come from the market data provider's split-adjusted history.

Value of an activity = `quantity × unitPrice` (fee separate). For DIVIDEND, the upstream
sample uses per-share price × shares held (`MSFT,…,0.62,5,dividend`). For FEE, the
sample puts the amount in `Fee` with `Price 0, Quantity 0`.

### Data source and symbols

- `DataSource` enum: `ALPHA_VANTAGE, COINGECKO, EOD_HISTORICAL_DATA,
  FINANCIAL_MODELING_PREP, GHOSTFOLIO, GOOGLE_SHEETS, MANUAL, RAPID_API, YAHOO`.
- If the column is blank or absent: `FEE`, `INTEREST` and `LIABILITY` default to `MANUAL`.
  `BUY`, `SELL` and `DIVIDEND` get the server's default import data source (normally
  `YAHOO`).
- With `MANUAL`, the client turns a free-text `Code` (e.g. `Account Opening Fee`) into a
  generated UUID symbol and keeps the text as the asset name. The server would reject a
  raw non-UUID MANUAL symbol that is not `GF_`-prefixed, but the client rewrites it first.
- ISIN symbols with a non-MANUAL data source are resolved to the provider symbol on the
  server.
- Yahoo symbols use Yahoo suffixes (`NESN.SW`, `VWCE.DE`, `BTCUSD`).

### Dates

`parseDate` in `libs/common/src/lib/helper.ts` tries, in order:
`dd-MM-yyyy`, `dd/MM/yyyy`, `dd.MM.yyyy`, `yyyy-MM-dd`, `yyyy/MM/dd`, `yyyy.MM.dd`,
`yyyyMMdd`, then falls back to ISO-8601 (`parseISO`). **US `MM/dd/yyyy` is not
supported** (it is read as `dd/MM/yyyy`). We write `yyyy-MM-dd`.

### Duplicates

The server flags a row as a duplicate when an existing activity matches on comment,
currency, dataSource, date (same second), fee, quantity, symbol, type and unitPrice.

### What statement2csv writes

Header taken from the upstream `test/import/ok/sample.csv`:

```csv
Date,Code,DataSource,Currency,Price,Quantity,Action,Fee,Note
2024-01-15,AAPL,,USD,185.5,10,buy,4.95,Initial purchase
2024-02-01,AAPL,,USD,0.24,10,dividend,0,Q4 dividend
2024-04-01,Interest,MANUAL,USD,12.5,1,interest,0,
2024-04-15,Fee,MANUAL,USD,0,0,fee,25,Account fee
```

Mapping from our model:

| Activity type | Ghostfolio row |
| ------------- | -------------- |
| BUY / SELL    | `buy`/`sell`, Code=symbol, DataSource blank, Price=unit_price, Quantity=quantity, Fee=fee |
| DIVIDEND      | `dividend`. If quantity and unit_price are known and quantity × unit_price equals amount (or amount is missing): use them. Otherwise Quantity=1, Price=amount. Fee=fee. |
| INTEREST      | `interest`, DataSource `MANUAL`, Code=symbol or `Interest`, Quantity=1, Price=amount |
| FEE           | `fee`, DataSource `MANUAL`, Code=symbol or `Fee`, Price=0, Quantity=0, Fee=amount (falls back to `fee` if amount is missing) |
| TAX           | **exported as `fee`** (no tax type in Ghostfolio), Code=symbol or `Tax`, comment prefixed `Tax`. This is our choice, not an upstream convention. |
| DEPOSIT / WITHDRAWAL / SPLIT | **skipped with a warning**. No equivalent activity type exists. |

`Account` is appended only when at least one activity has an account.

### Uncertainties

- Ghostfolio's own `ok.csv` examples were reported broken in the past
  (discussion #2647). The current `sample.csv` matches the current parser code.
- A DIVIDEND row with `Quantity=1, Price=total` is a common community convention, not an
  official one. Ghostfolio shows the same total either way.
- Treating TAX as FEE is our decision. Users who prefer to net withholding tax into the
  dividend can do that in the parser instead.
- If a symbol is not on the default data source (often YAHOO), the user must fix it in the
  import preview, or the parser must emit the provider symbol.

### Sources

- CSV parser (header names, type values, numeric rules): https://github.com/ghostfolio/ghostfolio/blob/main/apps/client/src/app/services/import-activities.service.ts
- Server import service (data source defaults, MANUAL symbols, duplicates): https://github.com/ghostfolio/ghostfolio/blob/main/apps/api/src/services/import/import.service.ts
- Date parsing: https://github.com/ghostfolio/ghostfolio/blob/main/libs/common/src/lib/helper.ts (`parseDate`)
- Enums `Type` and `DataSource`: https://github.com/ghostfolio/ghostfolio/blob/main/prisma/schema.prisma
- Investment vs non-investment types: https://github.com/ghostfolio/ghostfolio/blob/main/libs/common/src/lib/config.ts
- Sample CSV: https://github.com/ghostfolio/ghostfolio/blob/main/test/import/ok/sample.csv
- Import API (JSON fields): https://github.com/ghostfolio/ghostfolio#import-portfolio-data
- Past issue with the examples: https://github.com/ghostfolio/ghostfolio/discussions/2647
