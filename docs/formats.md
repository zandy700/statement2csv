# Target CSV import formats

This document records what statement2csv must output for each target app, and why.
It was researched on **2026-11-03** from the source code and docs of both projects.

| App         | Version checked                          | Commit                                     |
| ----------- | ---------------------------------------- | ------------------------------------------ |
| Wealthfolio | v3.12.0 (released 2026-11-01)            | `367615abd9db92a046b9d1fb65eb2c1ae33d8b47` |
| Ghostfolio  | 3.97.0 (released 2026-11-02)             | `fb8b12aa7eb2a9f28dc92ec18d7c951743782746` |

Both apps change their importers often. When upgrading, re-check the sources listed
at the end of each section.

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
2024-04-15,Account fee,MANUAL,USD,0,0,fee,25,
```

Mapping from our model:

| Activity type | Ghostfolio row |
| ------------- | -------------- |
| BUY / SELL    | `buy`/`sell`, Code=symbol, DataSource blank, Price=unit_price, Quantity=quantity, Fee=fee |
| DIVIDEND      | `dividend`. If quantity and unit_price are known: use them. Otherwise Quantity=1, Price=amount. Fee=fee. |
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
