"""Helpers shared by broker parsers.

The leading underscore keeps this module out of parser auto-discovery.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import warnings
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from statement2csv.models import Activity, ActivityType
from statement2csv.parsers.base import ParserError

# pdfminer logs a warning for every slightly malformed PDF object. That's noise for CLI users.
logging.getLogger("pdfminer").setLevel(logging.ERROR)

_EMPTY_MARKERS = {"", "-", "--", "\u2014", "\u2013", "n/a", "N/A"}
# Digits with correctly grouped thousands separators (or none), optional decimals.
_MONEY_RE = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)?(?:\.\d+)?$")


def parse_money(text: str | None) -> Decimal | None:
    """Parse a US-formatted signed number. Returns ``None`` for blank / dash cells.

    Handles ``$``, thousands separators, ``(1,234.56)`` and ``1,234.56-`` negatives,
    leading ``+``/``-`` and ``-$5.00`` / ``$-5.00`` / ``$ 5.00``. Rejects anything
    ambiguous (conflicting signs, badly grouped digits like ``12,34``, inner spaces such
    as two PDF words merged into one cell) with ``ValueError``.

    >>> parse_money("($1,234.50)")
    Decimal('-1234.50')
    """
    if text is None:
        return None
    s = text.strip().replace("\u2212", "-")  # unicode minus
    if s in _EMPTY_MARKERS:
        return None

    def invalid() -> ValueError:
        return ValueError(f"not a number: {text!r}")

    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
    if s.endswith("-"):
        if negative:
            raise invalid()
        negative, s = True, s[:-1].strip()
    # Sign and currency symbol may come in either order: "-$5", "$-5", "$ 5".
    sign_seen = False
    while s and s[0] in "+-$":
        char, s = s[0], s[1:].lstrip()
        if char == "$":
            continue
        if sign_seen or (char == "-" and negative):  # "--5", "(-5)", "-5-"
            raise invalid()
        sign_seen = True
        negative = negative or char == "-"
    if not any(c.isdigit() for c in s) or not _MONEY_RE.match(s):
        raise invalid()
    try:
        value = Decimal(s.replace(",", ""))
    except InvalidOperation as exc:  # pragma: no cover - regex guards this
        raise invalid() from exc
    return -value if negative else value


def parse_us_date(text: str) -> dt.date:
    """Parse ``MM/DD/YYYY`` or ``MM/DD/YY``."""
    s = text.strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"not a MM/DD/YYYY date: {text!r}")


def resolve_month_day(text: str, period_start: dt.date, period_end: dt.date) -> dt.date:
    """Turn a year-less ``MM/DD`` into a date inside the statement period.

    Handles periods that span a year end (e.g. 12/01/2023 - 01/31/2024).
    """
    month, day = (int(p) for p in text.strip().split("/")[:2])
    for year in range(period_start.year, period_end.year + 1):
        try:
            candidate = dt.date(year, month, day)
        except ValueError:
            continue
        if period_start <= candidate <= period_end:
            return candidate
    # Not in the period (e.g. a settlement date just after it). Pick the closest year.
    candidates = []
    for year in (period_start.year - 1, period_start.year, period_end.year, period_end.year + 1):
        try:
            candidates.append(dt.date(year, month, day))
        except ValueError:
            continue
    if not candidates:
        raise ValueError(f"invalid month/day: {text!r}")
    mid = period_start + (period_end - period_start) / 2
    return min(candidates, key=lambda d: abs(d - mid))


def resolve_statement_date(text: str, period_start: dt.date, period_end: dt.date) -> dt.date:
    """A statement date cell: ``MM/DD/YYYY`` (year kept as printed) or year-less ``MM/DD``."""
    if text.count("/") == 2:
        return parse_us_date(text)
    return resolve_month_day(text, period_start, period_end)


def pdf_pages_text(path: Path, max_pages: int | None = None) -> list[str]:
    """Extract text from each page of a PDF (layout-insensitive, line-ordered)."""
    import pdfplumber

    try:
        with pdfplumber.open(path) as pdf:
            pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
            return [page.extract_text() or "" for page in pages]
    except Exception as exc:
        raise ParserError(f"cannot read PDF {path.name}: {exc}") from exc


def pdf_first_page_text(path: Path) -> str:
    """Text of page 1, or ``""`` if the file isn't a readable PDF (for ``detect``)."""
    try:
        pages = pdf_pages_text(path, max_pages=1)
    except ParserError:
        return ""
    return pages[0] if pages else ""


# --- PDF words and lines (for table parsing from word positions) ----------------------


@dataclass
class PdfWord:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float


@dataclass
class PdfLine:
    words: list[PdfWord]

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.bottom for w in self.words)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def pdf_words(path: Path) -> list[list[PdfWord]]:
    """Words of every page, with their positions."""
    import pdfplumber

    try:
        with pdfplumber.open(path) as pdf:
            return [
                [
                    PdfWord(w["text"], w["x0"], w["x1"], w["top"], w["bottom"])
                    for w in page.extract_words()
                ]
                for page in pdf.pages
            ]
    except Exception as exc:
        raise ParserError(f"cannot read PDF {path.name}: {exc}") from exc


def group_lines(words: list[PdfWord], tolerance: float = 3.0) -> list[PdfLine]:
    """Group words into visual lines (tops within ``tolerance``), left to right."""
    lines: list[PdfLine] = []
    for word in sorted(words, key=lambda w: (w.top, w.x0)):
        if lines and abs(word.top - lines[-1].words[0].top) < tolerance:
            lines[-1].words.append(word)
        else:
            lines.append(PdfLine([word]))
    for line in lines:
        line.words.sort(key=lambda w: w.x0)
    return lines


# --- building activities consistently across parsers ---------------------------------

# Option trades: the normalized model has no contract multiplier, so they're skipped.
# Matched against the transaction description/action, never against security names
# (funds like "... COVERED CALL ETF" are ordinary securities).
_OPTION_ACTION_RE = re.compile(
    r"\bto\s+(open|close)\b|\b(opening|closing)\s+transaction\b|\bassigned\b|"
    r"\bexpired\b|\bexercised?\b|\b(BTO|STO|BTC|STC)\b",
    re.IGNORECASE,
)
# OCC option symbols ("AAPL240119C00190000", "AAPL 240119C190") and Schwab-style
# "AAPL 01/19/2024 190.00 C".
_OPTION_SYMBOL_RE = re.compile(
    r"^[A-Z.]{1,6}\s*\d{6}[CP]\d+(\.\d+)?$|\d{2}/\d{2}/\d{4}\s+[\d.]+\s+[CP]$"
)
# Option contract names, e.g. Fidelity's "PUT (AAPL) APPLE INC FEB 16 24 $180 (100 SHS)".
_OPTION_SECURITY_RE = re.compile(r"^(PUT|CALL)\s*\(|\(100 SHS\)", re.IGNORECASE)
_PRICE_DIGITS = Decimal("0.000001")


def is_option_trade(action: str, symbol: str | None, security: str = "") -> bool:
    return bool(
        _OPTION_ACTION_RE.search(action)
        or (symbol and _OPTION_SYMBOL_RE.search(symbol))
        or _OPTION_SECURITY_RE.search(security)
    )


def _close(a: Decimal, b: Decimal) -> bool:
    """Equal within rounding of printed prices: 0.5% or 5 cents."""
    return abs(a - b) <= max(Decimal("0.05"), abs(b) * Decimal("0.005"))


def reconcile_unit_price(
    activity_type: ActivityType,
    quantity: Decimal,
    price: Decimal | None,
    fee: Decimal,
    amount: Decimal | None,
) -> tuple[Decimal, str | None]:
    """Unit price consistent with the trade's cash amount, plus a warning if adjusted.

    ``quantity``, ``fee`` and ``amount`` are magnitudes. The cash amount is the source of
    truth: bonds/CDs/T-bills are priced per 100 of face value (price / 100 is used), and
    any other mismatch (e.g. an option's x100 multiplier) falls back to amount / quantity.
    """
    if amount is None:
        if price is None:
            raise ValueError("trade without a price or amount")
        return abs(price), None
    gross = amount - fee if activity_type is ActivityType.BUY else amount + fee
    if price is None:
        if gross <= 0:
            raise ValueError("trade without a price and a non-positive gross amount")
        return (gross / quantity).quantize(_PRICE_DIGITS), None
    price = abs(price)
    if gross <= 0 or _close(quantity * price, gross):
        return price, None
    if _close(quantity * price / 100, gross):
        return price / 100, None  # quoted per 100 of face value
    derived = (gross / quantity).quantize(_PRICE_DIGITS)
    return derived, (
        f"quantity x price ({quantity} x {price}) doesn't match the cash amount "
        f"({gross} before fees); using {derived} as unit price"
    )


def build_trade(
    *,
    broker: str,
    activity_type: ActivityType,
    date: dt.date,
    symbol: str | None,
    quantity: Decimal | None,
    price: Decimal | None,
    fee: Decimal | None,
    amount: Decimal | None,
    action: str,
    comment: str | None,
    context: str,
    security: str = "",
) -> Activity | None:
    """BUY/SELL from statement cells (any sign). Returns None (with a warning) to skip.

    Raises ``ValueError`` for rows missing essential fields.
    """
    if is_option_trade(action, symbol, security):
        warnings.warn(f"{broker}: skipping option trade (not supported): {context}", stacklevel=3)
        return None
    if quantity is None or quantity == 0:
        raise ValueError("trade without a quantity")
    if symbol is None:
        raise ValueError("trade without a symbol")
    quantity = abs(quantity)
    fee = abs(fee) if fee is not None else Decimal(0)
    amount = abs(amount) if amount is not None else None
    unit_price, problem = reconcile_unit_price(activity_type, quantity, price, fee, amount)
    if problem:
        warnings.warn(f"{broker}: {problem}: {context}", stacklevel=3)
    return Activity(
        date=date,
        symbol=symbol,
        activity_type=activity_type,
        quantity=quantity,
        unit_price=unit_price,
        fee=fee,
        amount=amount,
        currency="USD",
        comment=comment,
    )


#: Cash activity types whose statement amount is negative (cash leaves the account).
CASH_OUT_TYPES = frozenset({ActivityType.WITHDRAWAL, ActivityType.TAX, ActivityType.FEE})


def cash_sign_matches(activity_type: ActivityType, amount: Decimal) -> bool:
    """Does a signed statement amount point the way ``activity_type`` moves cash?

    A mismatch is a refund or reversal, which the model can't express.
    """
    return (amount < 0) == (activity_type in CASH_OUT_TYPES)
