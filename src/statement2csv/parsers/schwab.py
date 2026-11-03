"""Charles Schwab brokerage account statements (PDF), "Transaction Details" section.

Layout (current single-table Schwab One / brokerage statement):

* Every page starts with ``Schwab One(R) Account of <HOLDER>``, ``Account Number`` and
  ``Statement Period`` (``January 1-31, 2024``) and ends with a page counter and the
  ``Charles Schwab & Co., Inc. ... Member SIPC`` line.
* ``Transaction Details`` is one table, continued across pages under a
  ``Transaction Details (continued)`` title with repeated, two-line column headers
  (wrapped here)::

                             Symbol/                Price/Rate  Charges/
     Date Category Action CUSIP Description Quantity per Share($) Interest($) ...
     ...  Realized
     ...  Amount($) Gain/(Loss)($)

* Dates are year-less ``MM/DD``. Negatives are in parentheses. Rows of a group (e.g. a
  dividend and its foreign tax) may leave Date and Category blank. Long descriptions
  wrap onto extra lines. ``Total Transactions`` closes the table.

The table is read from word positions: column boundaries come from the header words, so
blank cells (no symbol, no quantity...) can't shift values into the wrong column.
Text columns are matched by their left edge, numeric columns by their right edge.

The older split layout ("Transaction Detail - Purchases & Sales", "... - Dividends &
Interest", ...) is not supported; such files raise ``ParserError``.
"""

from __future__ import annotations

import datetime as dt
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from statement2csv.models import Activity, ActivityType
from statement2csv.parsers._common import (
    PdfLine,
    PdfWord,
    build_trade,
    cash_sign_matches,
    group_lines,
    parse_money,
    parse_us_date,
    pdf_first_page_text,
    pdf_pages_text,
    pdf_words,
    resolve_month_day,
)
from statement2csv.parsers.base import BrokerParser, ParserError

# --- detection -----------------------------------------------------------------------

_FIRM_RE = re.compile(r"Charles\s+Schwab\s*&\s*Co\b", re.IGNORECASE)
_ACCOUNT_HEADER_RE = re.compile(r"Schwab\s+One\b|Account\s+of\b", re.IGNORECASE)
_PERIOD_LABEL_RE = re.compile(r"Statement\s+Period", re.IGNORECASE)
# Other brokers' statements can mention Schwab funds; never claim those.
_FOREIGN_RE = re.compile(
    r"Fidelity\s+Brokerage\s+Services|INVESTMENT\s+REPORT|Robinhood", re.IGNORECASE
)


def _looks_like_schwab(text: str) -> bool:
    return bool(
        _FIRM_RE.search(text)
        and _PERIOD_LABEL_RE.search(text)
        and _ACCOUNT_HEADER_RE.search(text)
        and not _FOREIGN_RE.search(text)
    )


# --- statement period ----------------------------------------------------------------

_MONTH = (
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
    r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
)
_DASH = r"\s*(?:-|\u2013|\u2014|to|through)\s*"
# "December 1, 2023 - January 31, 2024"
_PERIOD_FULL_RE = re.compile(
    rf"{_MONTH}\s+(\d{{1,2}}),\s*(\d{{4}}){_DASH}{_MONTH}\s+(\d{{1,2}}),\s*(\d{{4}})",
    re.IGNORECASE,
)
# "December 1 - January 31, 2024" / "January 1 - March 31, 2024"
_PERIOD_TWO_MONTHS_RE = re.compile(
    rf"{_MONTH}\s+(\d{{1,2}}){_DASH}{_MONTH}\s+(\d{{1,2}}),\s*(\d{{4}})", re.IGNORECASE
)
# "January 1-31, 2024"
_PERIOD_ONE_MONTH_RE = re.compile(
    rf"{_MONTH}\s+(\d{{1,2}})\s*(?:-|\u2013|\u2014)\s*(\d{{1,2}}),\s*(\d{{4}})", re.IGNORECASE
)
# "01/01/2024 - 01/31/2024"
_PERIOD_NUMERIC_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{2,4})" + _DASH + r"(\d{1,2}/\d{1,2}/\d{2,4})")


def _month_number(name: str) -> int:
    return dt.datetime.strptime(name[:3].title(), "%b").month


def _parse_period(text: str) -> tuple[dt.date, dt.date]:
    label = _PERIOD_LABEL_RE.search(text)
    # The value follows the label, possibly on the next line after other header values.
    windows = [text[label.end() : label.end() + 300]] if label else []
    windows.append(text)
    for window in windows:
        if m := _PERIOD_FULL_RE.search(window):
            start = dt.date(int(m[3]), _month_number(m[1]), int(m[2]))
            end = dt.date(int(m[6]), _month_number(m[4]), int(m[5]))
        elif m := _PERIOD_TWO_MONTHS_RE.search(window):
            end = dt.date(int(m[5]), _month_number(m[3]), int(m[4]))
            start_month = _month_number(m[1])
            start_year = end.year - 1 if start_month > end.month else end.year
            start = dt.date(start_year, start_month, int(m[2]))
        elif m := _PERIOD_ONE_MONTH_RE.search(window):
            month, year = _month_number(m[1]), int(m[4])
            start, end = dt.date(year, month, int(m[2])), dt.date(year, month, int(m[3]))
        elif m := _PERIOD_NUMERIC_RE.search(window):
            start, end = parse_us_date(m[1]), parse_us_date(m[2])
        else:
            continue
        if start <= end:
            return start, end
    raise ParserError("cannot find the Statement Period on page 1")


# --- table geometry ------------------------------------------------------------------

_TEXT_COLUMNS = ("date", "category", "action", "symbol", "description")
_NUM_COLUMNS = ("quantity", "price", "charges", "amount", "realized")
# Header words (either header line) -> column.
_HEADER_WORDS: dict[str, re.Pattern[str]] = {
    "date": re.compile(r"^Date$"),
    "category": re.compile(r"^Category$"),
    "action": re.compile(r"^Action$"),
    "symbol": re.compile(r"^(Symbol/?|CUSIP|Symbol/CUSIP)$"),
    "description": re.compile(r"^Description$"),
    "quantity": re.compile(r"^Quantity$"),
    "price": re.compile(r"^(Price/Rate|Price|per|Share\(\$\)|Rate)$"),
    "charges": re.compile(r"^(Charges/?|Interest\(\$\)|Charges/Interest\(\$\))$"),
    "amount": re.compile(r"^Amount(\(\$\))?$"),
    "realized": re.compile(r"^(Realized|Gain/\(Loss\)(\(\$\))?)$"),
}
_X_TOL = 2.0

_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}(/\d{2,4})?$")
# Case-sensitive and only checked in the Date column: wrapped descriptions are upper
# case and can start with "TOTAL" ("... TOTAL STOCK MARKET ETF").
_TOTAL_RE = re.compile(r"^Total\b")
# Lines that can sit right under the table on a page: page header/footer, notes.
_NOISE_RE = re.compile(
    # Case-sensitive on purpose: descriptions are upper case ("CHARLES SCHWAB CORP").
    r"\((?:continued|Continued)\)|^Page \d+ of \d+|^\d+ of \d+$|Member SIPC|"
    r"Charles Schwab & Co|Account Number|Statement Period|Account of|Endnotes"
)
_OLD_LAYOUT_RE = re.compile(
    r"Transaction\s+Detail\s*[-\u2013]\s*(Purchases|Deposits|Dividends)", re.IGNORECASE
)
_SECTION_RE = re.compile(r"Transaction\s+Details?\b", re.IGNORECASE)


@dataclass
class _Columns:
    text_left: dict[str, float]  # text column -> left edge
    num_bounds: list[tuple[str, float]]  # (numeric column, max x1), left to right
    numeric_zone: float  # words ending right of this belong to numeric columns

    def assign(self, line: PdfLine) -> dict[str, list[str]]:
        cells: dict[str, list[str]] = {}
        text_cols = sorted(self.text_left.items(), key=lambda kv: kv[1])
        for word in line.words:
            col: str | None = None
            if word.x1 > self.numeric_zone:
                col = next((c for c, bound in self.num_bounds if word.x1 <= bound), None)
            else:
                for name, left in text_cols:
                    if word.x0 + _X_TOL >= left:
                        col = name
                if col is None:  # left of the Date column
                    col = text_cols[0][0]
            if col is not None:
                cells.setdefault(col, []).append(word.text)
        return cells


def _find_header(lines: list[PdfLine], start: int) -> tuple[int, _Columns] | None:
    """Find the next Transaction Details column header at or after ``lines[start]``.

    Returns the index of the last header line and the column geometry.
    """
    for i in range(start, len(lines)):
        texts = {w.text for w in lines[i].words}
        if not {"Date", "Category", "Action"} <= texts:
            continue
        # Header labels may be split over two lines ("Price/Rate" over "per Share($)").
        group = [i]
        if i > 0 and lines[i].top - lines[i - 1].top <= 2.5 * (lines[i].bottom - lines[i].top):
            group.insert(0, i - 1)
        found: dict[str, list[PdfWord]] = {}
        for j in group:
            for word in lines[j].words:
                for col, pattern in _HEADER_WORDS.items():
                    if pattern.match(word.text):
                        found.setdefault(col, []).append(word)
                        break
        if not all(c in found for c in ("date", "category", "action", "amount", "quantity")):
            continue
        text_left = {c: min(w.x0 for w in found[c]) for c in _TEXT_COLUMNS if c in found}
        spans = [
            (c, min(w.x0 for w in found[c]), max(w.x1 for w in found[c]))
            for c in _NUM_COLUMNS
            if c in found
        ]
        spans.sort(key=lambda s: s[2])
        # Boundary between numeric columns: middle of the gutter between their labels.
        num_bounds = [
            (name, (right + spans[k + 1][1]) / 2 if k + 1 < len(spans) else float("inf"))
            for k, (name, _left, right) in enumerate(spans)
        ]
        numeric_zone = spans[0][1]
        return i, _Columns(text_left, num_bounds, numeric_zone)
    return None


# --- rows ----------------------------------------------------------------------------


@dataclass
class _Row:
    page: int
    cells: dict[str, list[str]] = field(default_factory=dict)

    def text(self, col: str) -> str:
        return " ".join(self.cells.get(col, []))

    def extend(self, cells: dict[str, list[str]]) -> None:
        for col, words in cells.items():
            self.cells.setdefault(col, []).extend(words)

    def describe(self) -> str:
        order = (*_TEXT_COLUMNS, *_NUM_COLUMNS)
        return " | ".join(self.text(c) for c in order if self.cells.get(c))


def _extract_rows(pages_words: list[list[PdfWord]]) -> tuple[bool, list[_Row]]:
    """Return (header found, raw rows) from all pages."""
    rows: list[_Row] = []
    header_found = False
    for page_no, words in enumerate(pages_words, start=1):
        lines = group_lines(words)
        pos = 0
        while (hit := _find_header(lines, pos)) is not None:
            header_found = True
            header_idx, cols = hit
            prev: PdfLine | None = None
            pos = header_idx + 1
            while pos < len(lines):
                line = lines[pos]
                cells = cols.assign(line)
                date_words = cells.get("date", [])
                if (date_words and _TOTAL_RE.match(date_words[0])) or _NOISE_RE.search(line.text):
                    break
                has_date = bool(cells.get("date")) and _DATE_RE.match(cells["date"][0])
                has_numbers = any(cells.get(c) for c in _NUM_COLUMNS)
                if has_date or has_numbers or cells.get("category"):
                    if cells.get("date") and not has_date:
                        break  # some other text in the Date column: end of table
                    rows.append(_Row(page_no, cells))
                elif (
                    rows
                    and rows[-1].page == page_no
                    and prev is not None
                    and line.top - prev.bottom <= 1.5 * (prev.bottom - prev.top) + 1
                ):
                    rows[-1].extend(cells)  # wrapped description / action
                else:
                    break
                prev = line
                pos += 1
    return header_found, rows


# --- classification ------------------------------------------------------------------

_REINVEST_BUY_RE = re.compile(r"reinvest\w*\s+shares?", re.IGNORECASE)
_BUY_RE = re.compile(r"^(buy|bought|purchase)\b", re.IGNORECASE)
_SELL_RE = re.compile(r"^(sell|sold|sale)\b", re.IGNORECASE)
_TAX_ACTION_RE = re.compile(
    r"\bnra\b|withh|\bw/h\b|foreign\s+tax|backup|tax\s+(adj|paid|w/?h|withheld)", re.IGNORECASE
)
_TAX_CATEGORY_RE = re.compile(r"\btax\b|withholding", re.IGNORECASE)
_FEE_ACTION_RE = re.compile(r"\bfees?\b|adr\s+(mgmt|pass)|service\s+charge", re.IGNORECASE)
_FEE_CATEGORY_RE = re.compile(r"\bfees?\b|expense", re.IGNORECASE)
_INTEREST_RE = re.compile(r"\binterest\b|\bint\b", re.IGNORECASE)
_DIVIDEND_RE = re.compile(r"\bdiv|dividend|cap(ital)?\s+gain", re.IGNORECASE)
# Cash-sweep bookkeeping: only when the *category* says so (an action like "Bank
# Transfer" under Category "Withdrawal" is a real withdrawal).
_SWEEP_CATEGORY_RE = re.compile(r"sweep", re.IGNORECASE)
# Not income: lowers cost basis (or corrects an earlier row); no matching activity type.
_UNSUPPORTED_RE = re.compile(
    r"return\s+of\s+capital|\bROC\b|div(idend)?\s+adj|cash\s+in\s+lieu", re.IGNORECASE
)
_DEPOSIT_RE = re.compile(r"funds\s+received|deposit|wire\s+received|moneylink\s+dep", re.I)
_WITHDRAWAL_RE = re.compile(
    r"funds\s+paid|withdraw|wire\s+(sent|funds)|moneylink\s+(transfer|txn)", re.IGNORECASE
)
_TRANSFER_RE = re.compile(r"transfer|journal|moneylink|wire", re.IGNORECASE)

_SKIP = "skip"


def _classify(category: str, action: str) -> ActivityType | str | None:
    """Map Category/Action to an activity type, ``_SKIP`` (silently ignored) or None."""
    if _UNSUPPORTED_RE.search(action):
        return None
    if _SWEEP_CATEGORY_RE.search(category):
        return ActivityType.INTEREST if _INTEREST_RE.search(action) else _SKIP
    if _REINVEST_BUY_RE.search(action) or _BUY_RE.match(action):
        return ActivityType.BUY
    if _SELL_RE.match(action):
        return ActivityType.SELL
    if _TAX_ACTION_RE.search(action):
        return ActivityType.TAX
    if _FEE_ACTION_RE.search(action):
        return ActivityType.FEE
    if _INTEREST_RE.search(action):
        return ActivityType.INTEREST
    if _DIVIDEND_RE.search(action):
        return ActivityType.DIVIDEND
    if _DEPOSIT_RE.search(action):
        return ActivityType.DEPOSIT
    if _WITHDRAWAL_RE.search(action):
        return ActivityType.WITHDRAWAL
    # Fall back to the category.
    if _BUY_RE.match(category):
        return ActivityType.BUY
    if _SELL_RE.match(category):
        return ActivityType.SELL
    if _TAX_CATEGORY_RE.search(category):
        return ActivityType.TAX
    if _FEE_CATEGORY_RE.search(category):
        return ActivityType.FEE
    if _INTEREST_RE.search(category):
        return ActivityType.INTEREST
    if _DIVIDEND_RE.search(category):
        return ActivityType.DIVIDEND
    if re.search(r"deposit", category, re.IGNORECASE):
        return ActivityType.DEPOSIT
    if re.search(r"withdrawal", category, re.IGNORECASE):
        return ActivityType.WITHDRAWAL
    if _TRANSFER_RE.search(action) or _TRANSFER_RE.search(category):
        return "transfer"  # direction from the amount's sign
    return None


# --- parser --------------------------------------------------------------------------


class SchwabParser(BrokerParser):
    name = "schwab"
    display_name = "Charles Schwab"
    file_types = (".pdf",)

    def detect(self, path: Path) -> bool:
        try:
            return _looks_like_schwab(pdf_first_page_text(path))
        except Exception:
            return False

    def parse(self, path: Path) -> list[Activity]:
        pages_text = pdf_pages_text(path)
        if not pages_text or not _looks_like_schwab(pages_text[0]):
            raise ParserError(f"{path.name} is not a Charles Schwab brokerage statement")
        period = _parse_period(pages_text[0])

        header_found, rows = _extract_rows(pdf_words(path))
        if not header_found:
            full_text = "\n".join(pages_text)
            if _OLD_LAYOUT_RE.search(full_text):
                raise ParserError(
                    f"{path.name}: the older split 'Transaction Detail - ...' layout "
                    "is not supported"
                )
            if _SECTION_RE.search(full_text):
                raise ParserError(
                    f"{path.name}: found 'Transaction Details' but not its column headers"
                )
            raise ParserError(f"{path.name}: no Transaction Details section found")

        activities: list[Activity] = []
        last_date: dt.date | None = None
        last_category = ""
        for row in rows:
            date_text = row.text("date")
            if row.text("category"):
                last_category = row.text("category")
            try:
                if date_text:
                    last_date = None  # don't attach this row to the previous date
                    last_date = resolve_month_day(date_text, *period)
                if last_date is None:
                    raise ValueError("no date")
                activity = self._to_activity(row, last_date, last_category)
            except (ValueError, TypeError) as exc:
                warnings.warn(f"Schwab: skipping row ({exc}): {row.describe()}", stacklevel=2)
                continue
            if activity is not None:
                activities.append(activity)
        return activities

    @staticmethod
    def _to_activity(row: _Row, date: dt.date, category: str) -> Activity | None:
        action = row.text("action")
        symbol = row.text("symbol").replace(" ", "") or None
        description = row.text("description")
        comment = description or action or category
        qty = parse_money(row.text("quantity"))
        price = parse_money(row.text("price"))
        charges = parse_money(row.text("charges"))
        amount = parse_money(row.text("amount"))

        kind = _classify(category, action)
        if kind == _SKIP:
            return None
        if kind is None:
            warnings.warn(
                f"Schwab: skipping unsupported transaction: {row.describe()}", stacklevel=3
            )
            return None

        if kind in (ActivityType.BUY, ActivityType.SELL):
            return build_trade(
                broker="Schwab",
                activity_type=kind,
                date=date,
                symbol=symbol,
                quantity=qty,
                price=price,
                fee=charges,
                amount=amount,
                action=action,
                comment=f"{action}: {description}" if description else action,
                context=row.describe(),
                security=description,
            )

        if amount is None or amount == 0:
            warnings.warn(
                f"Schwab: skipping transaction without a cash amount: {row.describe()}",
                stacklevel=3,
            )
            return None
        if kind == "transfer":
            kind = ActivityType.DEPOSIT if amount > 0 else ActivityType.WITHDRAWAL
        elif kind is ActivityType.INTEREST and amount < 0:
            kind = ActivityType.FEE  # e.g. margin interest charged
        if not cash_sign_matches(kind, amount):
            warnings.warn(
                f"Schwab: skipping {kind} with an unexpected sign (refund/reversal?): "
                f"{row.describe()}",
                stacklevel=3,
            )
            return None
        if kind is ActivityType.DIVIDEND and symbol is None:
            raise ValueError("dividend without a symbol")
        return Activity(
            date=date,
            symbol=symbol,
            activity_type=kind,
            amount=abs(amount),
            currency="USD",
            comment=comment,
        )
