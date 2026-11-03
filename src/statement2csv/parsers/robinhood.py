"""Robinhood "Account activity" CSV export (Reports & statements -> Reports).

File format (all fields quoted, UTF-8, optional BOM, rows newest first). Header::

    "Activity Date","Process Date","Settle Date","Instrument","Description",
    "Trans Code","Quantity","Price","Amount"

(one line in the file). Example records, one per line in the file, wrapped here::

    "2/15/2024","2/15/2024","2/15/2024","AAPL",
    "Cash Div: R/D 2024-02-12 P/D 2024-02-15 - 10 shares at 0.24","CDIV","","","$2.40"
    "1/16/2024","1/16/2024","1/18/2024","AAPL","Apple
    CUSIP: 037833100","Buy","10","$185.50","($1,855.00)"

The second record's Description really spans two lines inside the quotes.

* Dates are ``M/D/YYYY``. ``Price`` / ``Amount`` use ``$`` and thousands separators;
  cash out is in parentheses. ``Quantity`` can be fractional and occasionally carries a
  one-letter suffix (e.g. ``"5S"``), which is ignored.
* ``Description`` is often multi-line (name + ``CUSIP:`` line). Only its first line is
  kept as the comment.
* The file ends with a blank line and a disclaimer row (all columns empty except one
  free-text cell). Rows without an activity date and trans code are ignored.

Trans code mapping (anything else is skipped with a warning naming the row):

=====================  =============================================================
Buy / Sell             BUY / SELL (dividend reinvestments are plain ``Buy`` rows)
CDIV, MDIV             DIVIDEND (MDIV = manufactured dividend paid on lent shares)
INT, SLIP              INTEREST (SLIP = stock lending income)
MINT                   by sign: charged margin interest -> FEE, credit -> INTEREST
ACH, RTP               by sign: cash in -> DEPOSIT, cash out -> WITHDRAWAL
GOLD, AFEE, DFEE       FEE (Gold subscription, ADR / depositary fees)
DTAX                   TAX (dividend tax withholding)
GDBP, MTCH             DEPOSIT (Gold deposit boost, IRA match). These are bonuses from
                       Robinhood, not income from a holding. The normalized model has no
                       CREDIT type, so they are recorded as cash coming into the account.
SPL, SPR               SPLIT, only if the description states a ratio ("2 for 1", "1:10");
                       otherwise skipped (the export only shows the share delta)
=====================  =============================================================

Skipped with a warning: options (BTO, STC, BTC, STO, OEXP, OASGN, OEXCS, OCA),
journals / internal transfers (JNLC, JNLS, ITRF), ACATS transfers, trade
cancellations (BCXL, SCXL), corporate actions without cash/price data (REC, SXCH,
MRGS, MRGC, SOFF, CIL, ...) and any unknown code. Income codes with a negative amount
(reversals) and fee/tax codes with a positive amount (refunds) are skipped too, because
the model can't express the reversed direction. Cash rows with a zero amount and trades
with a zero quantity are skipped (as in the PDF parsers).

Fees on trades: Robinhood charges no commission, but sells carry regulatory (SEC/TAF)
fees netted into ``Amount``. ``amount`` is always the broker's cash total. For sells,
``fee`` is derived as ``round(quantity x price, 2) - |Amount|`` when that is positive and
within realistic SEC + TAF fee levels (0.01% of gross + $0.0003/share capped at $10 + 2
cents). Larger gaps (e.g. averaged fill prices) and all buys leave ``fee`` at 0.

Activities are returned oldest first. A row that can't be read (bad number or date,
missing Trans Code, dividend without Instrument...) is skipped with a warning; only a
file that isn't a Robinhood export (missing columns, broken CSV) raises ``ParserError``.
"""

from __future__ import annotations

import codecs
import csv
import datetime as dt
import io
import re
import warnings
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from statement2csv.models import Activity, ActivityType
from statement2csv.parsers._common import parse_money, parse_us_date
from statement2csv.parsers.base import BrokerParser, ParserError

COL_ACTIVITY_DATE = "Activity Date"
COL_INSTRUMENT = "Instrument"
COL_DESCRIPTION = "Description"
COL_CODE = "Trans Code"
COL_QUANTITY = "Quantity"
COL_PRICE = "Price"
COL_AMOUNT = "Amount"

#: Columns that must be present (Description is optional, used only for comments).
REQUIRED_COLUMNS = frozenset(
    {
        COL_ACTIVITY_DATE,
        "Process Date",
        "Settle Date",
        COL_INSTRUMENT,
        COL_CODE,
        COL_QUANTITY,
        COL_PRICE,
        COL_AMOUNT,
    }
)

_DETECT_BYTES = 4096
_CURRENCY = "USD"
_CENT = Decimal("0.01")
# Regulatory fees on a sell: SEC fee (a few $ per $100k, rate changes yearly) plus FINRA
# TAF (~$0.0002 per share, capped at a few $). Bound the derived fee by generous versions
# of both so a larger gap (e.g. averaged fill prices) is never booked as a fee.
_FEE_RATIO = Decimal("0.0001")
_FEE_PER_SHARE = Decimal("0.0003")
_FEE_PER_SHARE_CAP = Decimal("10")
_FEE_SLACK = Decimal("0.02")

_TRADE_CODES = {"BUY": ActivityType.BUY, "SELL": ActivityType.SELL}
#: Cash coming in. A negative amount is a reversal -> skipped.
_INCOME_CODES = {
    "CDIV": ActivityType.DIVIDEND,
    "MDIV": ActivityType.DIVIDEND,
    "INT": ActivityType.INTEREST,
    "SLIP": ActivityType.INTEREST,
    "GDBP": ActivityType.DEPOSIT,
    "MTCH": ActivityType.DEPOSIT,
}
#: Cash going out. A positive amount is a refund -> skipped.
_CHARGE_CODES = {
    "GOLD": ActivityType.FEE,
    "AFEE": ActivityType.FEE,
    "DFEE": ActivityType.FEE,
    "DTAX": ActivityType.TAX,
}
#: Direction depends on the sign of Amount: (if positive, if negative).
_SIGNED_CODES = {
    "ACH": (ActivityType.DEPOSIT, ActivityType.WITHDRAWAL),
    "RTP": (ActivityType.DEPOSIT, ActivityType.WITHDRAWAL),
    "MINT": (ActivityType.INTEREST, ActivityType.FEE),
}
_SPLIT_CODES = {"SPL", "SPR"}

_SKIP_REASONS = {
    **dict.fromkeys(
        ("BTO", "STC", "BTC", "STO", "OEXP", "OASGN", "OEXCS", "OCA"),
        "options are not supported",
    ),
    **dict.fromkeys(("JNLC", "JNLS", "ITRF"), "internal journal/transfer entry"),
    **dict.fromkeys(("ACATI", "ACATO", "ACATS"), "ACATS transfer; record the position manually"),
    **dict.fromkeys(
        ("BCXL", "SCXL"),
        "trade cancellation; remove the cancelled trade from the output manually",
    ),
}

_QUANTITY_RE = re.compile(r"^\s*(?P<num>[-+(]?[\d.,]+\)?)\s*[A-Za-z]?\s*$")
_RATIO_RE = re.compile(
    r"(?P<new>\d+(?:\.\d+)?)\s*(?:-?\s*for\s*-?|:)\s*(?P<old>\d+(?:\.\d+)?)", re.IGNORECASE
)


class RobinhoodParser(BrokerParser):
    name = "robinhood"
    display_name = "Robinhood"
    file_types = (".csv",)

    def detect(self, path: Path) -> bool:
        try:
            with path.open("rb") as fh:
                head = fh.read(_DETECT_BYTES)
            if not head or b"\x00" in head:
                return False
            # Incremental decoding tolerates a multibyte char cut at the 4 KB boundary.
            text = codecs.getincrementaldecoder("utf-8-sig")().decode(head, final=False)
            lines = text.splitlines()
            if not lines:
                return False
            header = next(csv.reader([lines[0]]), [])
            return {cell.strip() for cell in header} >= REQUIRED_COLUMNS
        except Exception:
            return False

    def parse(self, path: Path) -> list[Activity]:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            raise ParserError(f"cannot read {path.name}: {exc}") from exc

        reader = csv.reader(io.StringIO(text, newline=""))
        try:
            header = [cell.strip() for cell in next(reader)]
        except StopIteration:
            raise ParserError(f"{path.name} is empty") from None
        except csv.Error as exc:
            raise ParserError(f"{path.name}: malformed CSV header: {exc}") from exc
        missing = REQUIRED_COLUMNS - set(header)
        if missing:
            raise ParserError(
                f"{path.name} is not a Robinhood activity export: "
                f"missing column(s) {', '.join(sorted(missing))}"
            )
        index = {name: i for i, name in enumerate(header)}

        activities: list[Activity] = []
        row_no = 1
        line_no = reader.line_num + 1  # first physical line of the next record
        while True:
            row_no += 1
            try:
                row = next(reader)
            except StopIteration:
                break
            except csv.Error as exc:
                raise ParserError(
                    f"{path.name}: malformed CSV at row {row_no} (line {reader.line_num}): {exc}"
                ) from exc
            record = _Row(path.name, row_no, line_no, row, index)
            line_no = reader.line_num + 1
            if record.is_blank_or_footer():
                continue
            try:
                activity = record.to_activity()
            except (ParserError, ValueError) as exc:
                # A bad row is skipped (loudly), like in the PDF parsers; only a file that
                # isn't a Robinhood export at all raises.
                message = str(exc) if isinstance(exc, ParserError) else str(record.error(str(exc)))
                warnings.warn(f"{message}; row skipped", UserWarning, stacklevel=2)
                continue
            if activity is not None:
                activities.append(activity)
            elif record.skip_reason:
                warnings.warn(record.skip_reason, UserWarning, stacklevel=2)
        # The export is newest first. Return oldest first so same-day rows keep their real
        # order (a buy before the sell of those shares) through the exporters' date sort.
        activities.reverse()
        return activities


class _Row:
    """One CSV record plus its location, for error messages."""

    def __init__(
        self, source: str, row_no: int, line_no: int, cells: list[str], index: dict[str, int]
    ):
        self.source = source
        self.row_no = row_no
        self.line_no = line_no
        self.cells = cells
        self.index = index
        #: Set when the row is skipped. ``parse`` turns it into a warning.
        self.skip_reason: str | None = None

    def get(self, column: str) -> str:
        i = self.index.get(column)
        if i is None or i >= len(self.cells):
            return ""
        return self.cells[i].strip()

    @property
    def where(self) -> str:
        return f"{self.source} row {self.row_no} (line {self.line_no})"

    def label(self) -> str:
        parts = [self.get(COL_ACTIVITY_DATE), self.get(COL_CODE), self.get(COL_INSTRUMENT)]
        return " ".join(p for p in parts if p)

    def is_blank_or_footer(self) -> bool:
        # Covers empty lines and the trailing disclaimer row, which has text in one
        # column but no date and no trans code.
        return not self.get(COL_ACTIVITY_DATE) and not self.get(COL_CODE)

    def error(self, message: str) -> ParserError:
        return ParserError(f"Robinhood {self.where}: {message}")

    def skip(self, reason: str) -> None:
        self.skip_reason = f"Robinhood {self.where} [{self.label()}]: skipped, {reason}"

    # -- cell parsing -------------------------------------------------------

    def date(self) -> dt.date:
        raw = self.get(COL_ACTIVITY_DATE)
        try:
            return parse_us_date(raw)
        except ValueError:
            raise self.error(f"invalid Activity Date {raw!r}") from None

    def money(self, column: str) -> Decimal | None:
        raw = self.get(column)
        try:
            return parse_money(raw)
        except ValueError:
            raise self.error(f"invalid {column} {raw!r}") from None

    def quantity(self) -> Decimal | None:
        raw = self.get(COL_QUANTITY)
        if not raw:
            return None
        match = _QUANTITY_RE.match(raw)
        try:
            if match is None:
                raise ValueError(raw)
            value = parse_money(match["num"])
        except ValueError:
            raise self.error(f"invalid Quantity {raw!r}") from None
        return None if value is None else abs(value)

    def comment(self) -> str | None:
        description = self.get(COL_DESCRIPTION)
        return description.splitlines()[0].strip() if description else None

    # -- mapping ------------------------------------------------------------

    def to_activity(self) -> Activity | None:
        if len(self.cells) != len(self.index) and any(
            c.strip() for c in self.cells[len(self.index) :]
        ):
            raise self.error(f"expected {len(self.index)} columns, got {len(self.cells)}")
        code = self.get(COL_CODE).upper()
        date = self.date()
        if not code:
            raise self.error("missing Trans Code")

        if code in _TRADE_CODES:
            return self._trade(date, _TRADE_CODES[code])
        if code in _SPLIT_CODES:
            return self._split(date)
        if code in _INCOME_CODES or code in _CHARGE_CODES or code in _SIGNED_CODES:
            return self._cash(date, code)

        reason = _SKIP_REASONS.get(code, f"unsupported trans code {code!r}")
        self.skip(reason)
        return None

    def _require_amount(self) -> Decimal:
        amount = self.money(COL_AMOUNT)
        if amount is None:
            raise self.error(f"missing Amount for {self.get(COL_CODE)!r}")
        return amount

    def _trade(self, date: dt.date, activity_type: ActivityType) -> Activity:
        symbol = self.get(COL_INSTRUMENT)
        quantity = self.quantity()
        price = self.money(COL_PRICE)
        if not symbol:
            raise self.error("trade without Instrument")
        if quantity is None:
            raise self.error("trade without Quantity")
        if quantity == 0:
            raise self.error("trade with zero Quantity")
        if price is None:
            raise self.error("trade without Price")
        price = abs(price)
        amount = self.money(COL_AMOUNT)
        amount = None if amount is None else abs(amount)
        return Activity(
            date=date,
            symbol=symbol,
            activity_type=activity_type,
            quantity=quantity,
            unit_price=price,
            amount=amount,
            fee=_derive_fee(activity_type, quantity, price, amount),
            currency=_CURRENCY,
            comment=self.comment(),
        )

    def _split(self, date: dt.date) -> Activity | None:
        symbol = self.get(COL_INSTRUMENT)
        match = _RATIO_RE.search(self.get(COL_DESCRIPTION))
        if not symbol or match is None:
            self.skip("split ratio can't be determined from the export; add the split manually")
            return None
        new, old = Decimal(match["new"]), Decimal(match["old"])
        if new == 0 or old == 0:
            self.skip(f"invalid split ratio {match.group(0)!r}")
            return None
        return Activity(
            date=date,
            symbol=symbol,
            activity_type=ActivityType.SPLIT,
            amount=new / old,
            currency=_CURRENCY,
            comment=self.comment(),
        )

    def _cash(self, date: dt.date, code: str) -> Activity | None:
        amount = self._require_amount()
        if amount == 0:
            self.skip(f"zero amount on {code}")
            return None
        if code in _SIGNED_CODES:
            positive, negative = _SIGNED_CODES[code]
            activity_type = positive if amount >= 0 else negative
        elif code in _INCOME_CODES:
            if amount < 0:
                self.skip(f"negative amount on {code} (reversal) is not supported")
                return None
            activity_type = _INCOME_CODES[code]
        else:
            if amount > 0:
                self.skip(f"positive amount on {code} (refund) is not supported")
                return None
            activity_type = _CHARGE_CODES[code]

        symbol = self.get(COL_INSTRUMENT) or None
        if activity_type is ActivityType.DIVIDEND and symbol is None:
            raise self.error(f"{code} without Instrument")
        return Activity(
            date=date,
            symbol=symbol,
            activity_type=activity_type,
            amount=abs(amount),
            currency=_CURRENCY,
            comment=self.comment(),
        )


def _derive_fee(
    activity_type: ActivityType, quantity: Decimal, price: Decimal, amount: Decimal | None
) -> Decimal:
    """Regulatory fees netted into Amount (see module docstring). 0 if not derivable."""
    if activity_type is not ActivityType.SELL or amount is None:
        return Decimal(0)
    gross = (quantity * price).quantize(_CENT, rounding=ROUND_HALF_UP)
    gap = gross - amount
    tolerance = gross * _FEE_RATIO + min(quantity * _FEE_PER_SHARE, _FEE_PER_SHARE_CAP) + _FEE_SLACK
    if 0 < gap <= tolerance:
        return gap
    return Decimal(0)
