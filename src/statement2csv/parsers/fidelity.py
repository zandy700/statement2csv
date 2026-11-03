"""Fidelity brokerage monthly statements ("INVESTMENT REPORT", PDF), "Activity" section.

Layout assumptions (publicly known Fidelity brokerage statement):

* Page 1 shows ``INVESTMENT REPORT`` with the period (``February 1, 2024 - February 29,
  2024``), the holder, ``Account Number: Z12-345678`` and an Account Summary. Every page
  ends with a footer naming ``Fidelity Brokerage Services LLC ... Member NYSE, SIPC`` and
  ``Page N of M``; later pages repeat a short header (holder, account number,
  ``INVESTMENT REPORT``, period).
* Holdings come first, then an ``Activity`` heading (``Activity (continued)`` on later
  pages) with subsections, each a table with its own column headers and closed by
  ``Total ...`` / ``Net ...`` rows:

  - ``Securities Bought & Sold``: Settlement Date | Security Name | Symbol/CUSIP |
    Description (``You Bought``, ``You Sold``, ``Reinvestment``) | Quantity | Price |
    Transaction Cost | Amount
  - ``Dividends, Interest & Other Income``: same without Transaction Cost. Descriptions
    ``Dividend Received``, ``Interest Earned``, ``Long-Term Cap Gain``, ``Foreign Tax
    Paid``; a dividend reinvestment shows both legs (``Dividend Received`` + a
    ``Reinvestment`` row with quantity/price) -> DIVIDEND + BUY.
  - ``Deposits`` / ``Withdrawals``: Date | Reference | Description | Amount
  - ``Fees and Charges`` (and ``Taxes Withheld``): Date | Description | Amount
  - ``Core Fund Activity``: money-market sweep bookkeeping, ignored.
  - ``Trades Pending Settlement``: ignored with a warning (they settle, and are reported,
    next period). Other subsections (``Other Activity In``...) are classified by their
    description.

* Long security names wrap onto extra lines. Two-line column headers are common
  (``Settlement`` over ``Date``, ``Symbol/`` over ``CUSIP``, ``Transaction`` over
  ``Cost``). Dates are year-less ``MM/DD``. Negatives use a leading ``-`` (parentheses
  are accepted too); empty numeric cells print ``-``.
* A subsection continuing on the next page repeats its title with ``(continued)`` and
  its column headers; page headers/footers in between are skipped.
* The Activity section ends at ``Estimated Cash Flow`` / ``Additional Information...``.

Tables are read from word positions: column boundaries come from the header words, so
blank cells can't shift values into the wrong column. Text columns are matched by their
left edge, numeric columns by their right edge.

Mapping: capital gain distributions -> DIVIDEND; negative interest -> FEE; refunds or
reversals (positive tax/fee, negative dividend/deposit...) are skipped with a warning.
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

_REPORT_RE = re.compile(r"INVESTMENT\s+REPORT", re.IGNORECASE)
_FIRM_RE = re.compile(
    r"Fidelity\s+Brokerage\s+Services|Fidelity\s+Investments|"
    r"National\s+Financial\s+Services",
    re.IGNORECASE,
)
# Other brokers' statements can mention Fidelity funds; never claim those.
_FOREIGN_RE = re.compile(r"Charles\s+Schwab\s*&\s*Co\b|Robinhood", re.IGNORECASE)

# --- statement period ----------------------------------------------------------------

_MONTH = (
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
    r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
)
_DASH = r"\s*(?:-|\u2013|\u2014|to|through)\s*"
# "February 1, 2024 - February 29, 2024"
_PERIOD_FULL_RE = re.compile(
    rf"{_MONTH}\s+(\d{{1,2}}),\s*(\d{{4}}){_DASH}{_MONTH}\s+(\d{{1,2}}),\s*(\d{{4}})",
    re.IGNORECASE,
)
# "02/01/2024 - 02/29/2024"
_PERIOD_NUMERIC_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})" + _DASH + r"(\d{1,2}/\d{1,2}/\d{4})")


def _month_number(name: str) -> int:
    return dt.datetime.strptime(name[:3].title(), "%b").month


def _find_period(text: str) -> tuple[dt.date, dt.date] | None:
    candidates: list[tuple[int, dt.date, dt.date]] = []
    for m in _PERIOD_FULL_RE.finditer(text):
        try:
            start = dt.date(int(m[3]), _month_number(m[1]), int(m[2]))
            end = dt.date(int(m[6]), _month_number(m[4]), int(m[5]))
        except ValueError:
            continue
        candidates.append((m.start(), start, end))
    for m in _PERIOD_NUMERIC_RE.finditer(text):
        try:
            candidates.append((m.start(), parse_us_date(m[1]), parse_us_date(m[2])))
        except ValueError:
            continue
    for _pos, start, end in sorted(candidates, key=lambda c: c[0]):
        if start <= end:
            return start, end
    return None


def _looks_like_fidelity(text: str) -> bool:
    return bool(
        _REPORT_RE.search(text)
        and _FIRM_RE.search(text)
        and not _FOREIGN_RE.search(text)
        and _find_period(text) is not None
    )


# --- page structure ------------------------------------------------------------------

_ACTIVITY_RE = re.compile(r"^Activity(\s*\(continued\))?$")
# Headings that close the Activity section.
_END_RE = re.compile(
    r"^(Estimated Cash Flow|Additional Information|Information About Your|"
    r"Daily Additions and Subtractions|Holdings|Income Summary|Realized Gain/Loss|"
    r"Important Information)\b"
)
_TITLE_TAIL = r"(\s*\(.*\))?$"  # "(continued)", "(Includes dividend reinvestment)"
# Case-sensitive: security names are upper case and may wrap ("SHORT TERM ...").
_SECTION_TITLES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^Securities Bought (&|and) Sold" + _TITLE_TAIL), "trades"),
    (re.compile(r"^Dividends, Interest (&|and) Other Income" + _TITLE_TAIL), "income"),
    (re.compile(r"^Deposits" + _TITLE_TAIL), "deposits"),
    (re.compile(r"^Withdrawals" + _TITLE_TAIL), "withdrawals"),
    (re.compile(r"^Fees (and|&) Charges" + _TITLE_TAIL), "fees"),
    (re.compile(r"^Taxes Withheld" + _TITLE_TAIL), "taxes"),
    (re.compile(r"^Core Fund Activity" + _TITLE_TAIL), "core"),
    (re.compile(r"^Trades Pending Settlement" + _TITLE_TAIL), "pending"),
    (re.compile(r"^Other Activity (In|Out)" + _TITLE_TAIL), "other"),
]
# Page header/footer lines. Case-sensitive on purpose (security names are upper case).
_NOISE_RE = re.compile(
    r"Fidelity Brokerage Services|National Financial Services|INVESTMENT REPORT|"
    r"Account Number|Account #|\bPage \d+ of \d+|^\d+ of \d+$"
)
_TOTAL_RE = re.compile(r"^(Total|Net)\b")
_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}(/\d{2,4})?$")
_NUMERIC_WORD_RE = re.compile(r"^[$()+\-\u2212\d.,%]+$")
_MONEY_TAIL_RE = re.compile(r"\(?-?\$?[\d,]+\.\d{2}\)?-?$")

# --- table geometry ------------------------------------------------------------------

_TEXT_COLUMNS = (
    "date",
    "security",
    "symbol",
    "account_type",
    "transaction",
    "reference",
    "description",
)
_NUM_COLUMNS = ("quantity", "price", "cost", "amount", "balance")
# Merged header label (top line + bottom line) -> column.
_LABELS: list[tuple[str, re.Pattern[str]]] = [
    ("cost", re.compile(r"^Transaction Cost$")),
    ("date", re.compile(r"^((Settlement|Trade|Transaction) )?Date$")),
    ("security", re.compile(r"^Security( Name| Description)?$")),
    ("symbol", re.compile(r"^(Symbol/ ?CUSIP|Symbol/?|CUSIP)$")),
    ("account_type", re.compile(r"^Account Type$")),
    ("transaction", re.compile(r"^Transaction$")),
    ("reference", re.compile(r"^Reference$")),
    ("description", re.compile(r"^Description$")),
    ("quantity", re.compile(r"^Quantity$")),
    ("price", re.compile(r"^Price( Per Unit)?$")),
    ("amount", re.compile(r"^Amount$")),
    ("balance", re.compile(r"^Balance$")),
]
# Words allowed on the upper line of a two-line column header.
_HEADER_VOCAB = frozenset(
    {
        "Settlement",
        "Trade",
        "Symbol/",
        "Symbol",
        "CUSIP",
        "Symbol/CUSIP",
        "Security",
        "Name",
        "Account",
        "Type",
        "Transaction",
        "Cost",
        "Date",
        "Description",
        "Reference",
        "Quantity",
        "Price",
        "Per",
        "Unit",
        "Amount",
        "Balance",
    }
)
_X_TOL = 2.0
_WORD_GAP = 4.0  # max gap between words of one header label


@dataclass
class _Columns:
    text_left: dict[str, float]  # text column -> left edge
    num_bounds: list[tuple[str, float]]  # (numeric column, max x1), left to right
    numeric_zone: float  # numeric-looking words ending right of this are numbers

    def assign(self, line: PdfLine) -> dict[str, list[str]]:
        cells: dict[str, list[str]] = {}
        text_cols = sorted(self.text_left.items(), key=lambda kv: kv[1])
        for word in line.words:
            col: str | None = None
            if word.x1 > self.numeric_zone and _NUMERIC_WORD_RE.match(word.text):
                col = next((c for c, bound in self.num_bounds if word.x1 <= bound), None)
            elif text_cols:
                col = text_cols[0][0]  # left of the first column: first column
                for name, left in text_cols:
                    if word.x0 + _X_TOL >= left:
                        col = name
            if col is not None:
                cells.setdefault(col, []).append(word.text)
        return cells


def _phrases(line: PdfLine) -> list[list[PdfWord]]:
    """Split a header line into labels: runs of words separated by a single space."""
    groups: list[list[PdfWord]] = []
    for word in line.words:
        if groups and word.x0 - groups[-1][-1].x1 <= _WORD_GAP:
            groups[-1].append(word)
        else:
            groups.append([word])
    return groups


def _overlap(a: list[PdfWord], b: list[PdfWord]) -> float:
    return min(a[-1].x1, b[-1].x1) - max(a[0].x0, b[0].x0)


def _is_header_trigger(line: PdfLine) -> bool:
    texts = {w.text for w in line.words}
    return "Date" in texts and "Amount" in texts


def _is_upper_header_line(lines: list[PdfLine], i: int) -> bool:
    """Is ``lines[i]`` the upper line of a two-line column header ending at ``i + 1``?"""
    if i + 1 >= len(lines) or not _is_header_trigger(lines[i + 1]):
        return False
    upper, lower = lines[i], lines[i + 1]
    return lower.top - upper.top <= 2.5 * (lower.bottom - lower.top) and all(
        w.text in _HEADER_VOCAB for w in upper.words
    )


def _parse_header(lines: list[PdfLine], i: int) -> tuple[int, _Columns] | None:
    """Column geometry from the header whose bottom line is ``lines[i]``.

    Returns the index of the first header line and the columns.
    """
    labels = _phrases(lines[i])
    first = i
    if i > 0 and _is_upper_header_line(lines, i - 1):
        first = i - 1
        merged = [list(lbl) for lbl in labels]
        extra: list[list[PdfWord]] = []
        for top in _phrases(lines[i - 1]):
            best = max(range(len(merged)), key=lambda k: _overlap(top, merged[k]))
            if _overlap(top, merged[best]) > 0:
                merged[best] = top + merged[best]
            else:
                extra.append(top)
        labels = merged + extra

    found: dict[str, tuple[float, float]] = {}
    for label in labels:
        text = " ".join(w.text for w in label)
        for col, pattern in _LABELS:
            if pattern.match(text) and col not in found:
                found[col] = (min(w.x0 for w in label), max(w.x1 for w in label))
                break
    if "date" not in found or "amount" not in found:
        return None
    text_left = {c: found[c][0] for c in _TEXT_COLUMNS if c in found}
    spans = sorted(((c, *found[c]) for c in _NUM_COLUMNS if c in found), key=lambda s: s[2])
    # Boundary between numeric columns: middle of the gutter between their labels.
    num_bounds = [
        (name, (right + spans[k + 1][1]) / 2 if k + 1 < len(spans) else float("inf"))
        for k, (name, _left, right) in enumerate(spans)
    ]
    return first, _Columns(text_left, num_bounds, spans[0][1])


def _section_for(title_line: PdfLine | None, current: str | None) -> str | None:
    """Subsection key for a table whose header follows ``title_line``."""
    if title_line is None or _NOISE_RE.search(title_line.text):
        return current  # continued on a new page without a repeated title
    text = title_line.text.strip()
    for pattern, key in _SECTION_TITLES:
        if pattern.match(text):
            return key
    if _ACTIVITY_RE.match(text) and "continued" in text:
        return current
    return "other"


def _section_title(text: str) -> str | None:
    for pattern, key in _SECTION_TITLES:
        if pattern.match(text):
            return key
    return None


# --- rows ----------------------------------------------------------------------------


@dataclass
class _Row:
    page: int
    table: int
    section: str
    cells: dict[str, list[str]] = field(default_factory=dict)

    def text(self, col: str) -> str:
        return " ".join(self.cells.get(col, []))

    def extend(self, cells: dict[str, list[str]]) -> None:
        for col, words in cells.items():
            self.cells.setdefault(col, []).extend(words)

    def describe(self) -> str:
        order = (*_TEXT_COLUMNS, *_NUM_COLUMNS)
        return " | ".join(self.text(c) for c in order if self.cells.get(c))


@dataclass
class _Extraction:
    activity_found: bool = False
    header_found: bool = False
    rows: list[_Row] = field(default_factory=list)


def _extract_rows(pages_words: list[list[PdfWord]]) -> _Extraction:
    result = _Extraction()
    rows = result.rows
    in_activity = False
    section: str | None = None
    cols: _Columns | None = None
    table_id = 0
    prev: PdfLine | None = None
    for page_no, words in enumerate(pages_words, start=1):
        lines = group_lines(words)
        for idx, line in enumerate(lines):
            text = line.text.strip()
            if _NOISE_RE.search(text) or _PERIOD_FULL_RE.search(text):
                cols, prev = None, None  # page header/footer: a table can only resume
                continue  # after its repeated column headers
            if _ACTIVITY_RE.match(text):
                in_activity = result.activity_found = True
                cols, prev = None, None
                continue
            if not in_activity:
                continue
            if _END_RE.match(text):
                in_activity, cols, prev = False, None, None
                continue
            if _section_title(text) is not None or _is_upper_header_line(lines, idx):
                cols, prev = None, None
                continue
            if _is_header_trigger(line) and (hit := _parse_header(lines, idx)) is not None:
                first, cols = hit
                result.header_found = True
                section = _section_for(lines[first - 1] if first > 0 else None, section)
                table_id += 1
                prev = None
                continue
            if cols is None:
                if _DATE_RE.match(line.words[0].text) and _MONEY_TAIL_RE.search(text):
                    warnings.warn(
                        f"Fidelity: skipping line outside a recognized table: {text}",
                        stacklevel=3,
                    )
                continue
            if _TOTAL_RE.match(text):
                cols, prev = None, None
                continue

            cells = cols.assign(line)
            date_words = cells.get("date", [])
            has_date = bool(date_words) and bool(_DATE_RE.match(date_words[0]))
            numeric = [c for c in _NUM_COLUMNS if cells.get(c)]
            last = rows[-1] if rows and rows[-1].table == table_id else None
            close = (
                prev is not None
                and last is not None
                and line.top - prev.bottom <= 1.5 * (prev.bottom - prev.top) + 1
            )
            if has_date:
                rows.append(_Row(page_no, table_id, section or "other", cells))
            elif date_words and not numeric and not close:
                cols, prev = None, None  # other text in the Date column: end of table
                continue
            elif numeric:
                if close and last is not None and not any(last.cells.get(c) for c in numeric):
                    last.extend(cells)  # numbers printed on a wrapped row's 2nd line
                else:
                    warnings.warn(f"Fidelity: skipping line without a date: {text}", stacklevel=3)
            elif close and last is not None:
                last.extend(cells)  # wrapped security name / description
            else:
                cols, prev = None, None
                continue
            prev = line
    return result


# --- classification ------------------------------------------------------------------

_REINVEST_RE = re.compile(r"^Reinvest", re.IGNORECASE)
_BUY_RE = re.compile(r"^(You\s+)?(Bought|Buy|Purchased?)\b", re.IGNORECASE)
_SELL_RE = re.compile(r"^(You\s+)?(Sold|Sell|Sale)\b", re.IGNORECASE)
_TAX_RE = re.compile(r"foreign\s+tax|tax\s+(withheld|paid|w/?h)|withholding|\bnra\b", re.IGNORECASE)
_FEE_RE = re.compile(r"\bfees?\b|\bcharges?\b", re.IGNORECASE)
_INTEREST_RE = re.compile(r"\binterest\b", re.IGNORECASE)
_DIVIDEND_RE = re.compile(r"dividend|cap(ital)?\s+gain|\bdistribution\b", re.IGNORECASE)
_DEPOSIT_RE = re.compile(
    r"transfer\s+received|check\s+received|wire\s+transfer\s+from|deposit|"
    r"funds\s+received",
    re.IGNORECASE,
)
_WITHDRAWAL_RE = re.compile(
    r"transfer\s+paid|wire\s+transfer\s+to|withdrawal|check\s+paid|bill\s+payment|"
    r"debit\s+card",
    re.IGNORECASE,
)
_SECTION_TYPES = {
    "deposits": ActivityType.DEPOSIT,
    "withdrawals": ActivityType.WITHDRAWAL,
    "fees": ActivityType.FEE,
    "taxes": ActivityType.TAX,
}
_TRAILING_SYMBOL_RE = re.compile(r"\(([A-Z0-9.]{1,12})\)\s*$")


def _classify(section: str, description: str) -> ActivityType | None:
    if section in _SECTION_TYPES:
        return _SECTION_TYPES[section]
    if _REINVEST_RE.search(description) or _BUY_RE.match(description):
        return ActivityType.BUY
    if _SELL_RE.match(description):
        return ActivityType.SELL
    if _TAX_RE.search(description):
        return ActivityType.TAX
    if _FEE_RE.search(description):
        return ActivityType.FEE
    if _INTEREST_RE.search(description):
        return ActivityType.INTEREST
    if _DIVIDEND_RE.search(description):
        return ActivityType.DIVIDEND
    if _DEPOSIT_RE.search(description):
        return ActivityType.DEPOSIT
    if _WITHDRAWAL_RE.search(description):
        return ActivityType.WITHDRAWAL
    return None


def _symbol(row: _Row) -> str | None:
    symbol = row.text("symbol").replace(" ", "")
    if symbol and symbol not in ("-", "--"):
        return symbol
    if m := _TRAILING_SYMBOL_RE.search(row.text("security")):
        return m[1]
    return None


# --- parser --------------------------------------------------------------------------


class FidelityParser(BrokerParser):
    name = "fidelity"
    display_name = "Fidelity"
    file_types = (".pdf",)

    def detect(self, path: Path) -> bool:
        try:
            return _looks_like_fidelity(pdf_first_page_text(path))
        except Exception:
            return False

    def parse(self, path: Path) -> list[Activity]:
        pages_text = pdf_pages_text(path)
        if not pages_text or not _looks_like_fidelity(pages_text[0]):
            raise ParserError(f"{path.name} is not a Fidelity INVESTMENT REPORT statement")
        period = _find_period(pages_text[0])
        if period is None:  # pragma: no cover - _looks_like_fidelity checks it
            raise ParserError(f"{path.name}: cannot find the statement period on page 1")

        extraction = _extract_rows(pdf_words(path))
        if not extraction.activity_found:
            raise ParserError(f"{path.name}: no Activity section found")
        if not extraction.header_found:
            raise ParserError(
                f"{path.name}: found 'Activity' but no recognizable transaction table"
            )

        activities: list[Activity] = []
        for row in extraction.rows:
            if row.section == "core":
                continue  # money-market sweep bookkeeping, not portfolio activity
            if row.section == "pending":
                warnings.warn(
                    "Fidelity: skipping trade pending settlement (reported on the next "
                    f"statement): {row.describe()}",
                    stacklevel=2,
                )
                continue
            try:
                date_text = row.text("date")
                date = (
                    parse_us_date(date_text)
                    if date_text.count("/") == 2
                    else resolve_month_day(date_text, *period)
                )
                activity = self._to_activity(row, date)
            except (ValueError, TypeError) as exc:
                warnings.warn(f"Fidelity: skipping row ({exc}): {row.describe()}", stacklevel=2)
                continue
            if activity is not None:
                activities.append(activity)
        return activities

    @staticmethod
    def _to_activity(row: _Row, date: dt.date) -> Activity | None:
        description = row.text("description") or row.text("transaction")
        security = row.text("security")
        reference = row.text("reference")
        symbol = _symbol(row)
        qty = parse_money(row.text("quantity"))
        price = parse_money(row.text("price"))
        cost = parse_money(row.text("cost"))
        amount = parse_money(row.text("amount"))

        kind = _classify(row.section, description)
        if kind is None:
            warnings.warn(
                f"Fidelity: skipping unsupported transaction: {row.describe()}", stacklevel=3
            )
            return None

        if kind in (ActivityType.BUY, ActivityType.SELL):
            return build_trade(
                broker="Fidelity",
                activity_type=kind,
                date=date,
                symbol=symbol,
                quantity=qty,
                price=price,
                fee=cost,
                amount=amount,
                action=description,
                comment=f"{description}: {security}" if security else description,
                context=row.describe(),
                security=security,
            )

        if amount is None or amount == 0:
            warnings.warn(
                f"Fidelity: skipping transaction without a cash amount: {row.describe()}",
                stacklevel=3,
            )
            return None
        if kind is ActivityType.INTEREST and amount < 0:
            kind = ActivityType.FEE  # e.g. margin interest charged
        if not cash_sign_matches(kind, amount):
            warnings.warn(
                f"Fidelity: skipping {kind} with an unexpected sign (refund/reversal?): "
                f"{row.describe()}",
                stacklevel=3,
            )
            return None
        if kind is ActivityType.DIVIDEND and symbol is None:
            raise ValueError("dividend without a symbol")
        comment = f"{description}: {security}" if security else description
        if reference:
            comment = f"{comment} ({reference})"
        return Activity(
            date=date,
            symbol=symbol,
            activity_type=kind,
            amount=abs(amount),
            currency="USD",
            comment=comment,
        )
