"""Realized capital gains report (FIFO), laid out like IRS Form 8949.

See docs/formats.md#gains.

NOT TAX ADVICE. This is an estimate from the activities in the statements you
convert. Your broker's Form 1099-B is authoritative; use it to file.

How it works:

* Each BUY opens a lot. Its cost basis is the broker's total paid (``amount``) or, if
  the statement doesn't show it, quantity x price + fee.
* Each SELL closes shares first-in, first-out from the open lots of the same symbol
  in the same account and currency. Net proceeds are ``amount`` or quantity x
  price - fee. When a sell closes several lots (or part of one), proceeds and basis
  are split by quantity, and every lot gets its own row.
* On the same date, buys are matched before sells, so day trades work whatever order
  the statement lists them in.
* A SPLIT multiplies the open lots' share counts by the ratio; basis is unchanged.
* A sale is long-term when the shares were held more than one year: sold after the
  one-year anniversary of the purchase date.
* Shares sold without enough earlier buys (usually bought before the first statement
  you converted) get a row with a blank date acquired, basis and gain, and a warning.

Not handled: wash sales, short sales, options, corporate actions other than splits,
gifted or inherited shares, and specific-lot elections other than FIFO.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import ClassVar

from statement2csv.exporters.base import Cell, Exporter, ExportResult, Table, fmt_decimal
from statement2csv.models import Activity, ActivityType

COLUMNS = [
    "description",
    "date_acquired",
    "date_sold",
    "proceeds",
    "cost_basis",
    "gain_loss",
    "term",
]

SHORT, LONG, UNKNOWN = "short", "long", "unknown"

DISCLAIMER = (
    "Not tax advice. These figures are an estimate (FIFO, no wash-sale adjustments) from "
    "the statements you converted. Your broker's Form 1099-B is authoritative."
)

ZERO = Decimal(0)
CENT = Decimal("0.01")

# Same-day processing order: open lots before closing them.
_ORDER = {ActivityType.SPLIT: 0, ActivityType.BUY: 1, ActivityType.SELL: 2}

LotKey = tuple[str | None, str, str]  # (account, symbol, currency)


def money(value: Decimal) -> Decimal:
    """Round to cents (``+ 0`` turns ``-0.00`` into ``0.00``)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP) + 0


def one_year_after(day: dt.date) -> dt.date:
    """Same calendar date one year later (Feb 29 -> Feb 28)."""
    try:
        return day.replace(year=day.year + 1)
    except ValueError:
        return day.replace(year=day.year + 1, day=28)


def holding_term(acquired: dt.date, sold: dt.date) -> str:
    """``"long"`` if held more than one year, else ``"short"``."""
    return LONG if sold > one_year_after(acquired) else SHORT


def buy_cost(activity: Activity) -> Decimal:
    """Total cost of a BUY, fees included."""
    if activity.amount is not None:
        return activity.amount
    return activity.quantity * activity.unit_price + activity.fee


def sell_proceeds(activity: Activity) -> Decimal:
    """Net proceeds of a SELL, fees subtracted."""
    if activity.amount is not None:
        return activity.amount
    return activity.quantity * activity.unit_price - activity.fee


@dataclass
class Lot:
    acquired: dt.date
    quantity: Decimal
    basis: Decimal

    def take(self, quantity: Decimal) -> Decimal:
        """Remove ``quantity`` shares from the lot and return their basis.

        A partial take gets whole cents; the last take gets what is left, so the rows
        for one lot add up to its basis exactly.
        """
        if quantity >= self.quantity:
            basis = self.basis
            self.quantity, self.basis = ZERO, ZERO
            return basis
        basis = money(self.basis * quantity / self.quantity)
        self.quantity -= quantity
        self.basis -= basis
        return basis


@dataclass
class Disposal:
    """One Form 8949 line: (part of) a sale matched to one lot, or to no lot."""

    sale: Activity
    quantity: Decimal
    acquired: dt.date | None
    proceeds: Decimal
    basis: Decimal | None

    @property
    def symbol(self) -> str:
        return self.sale.symbol or ""

    @property
    def sold(self) -> dt.date:
        return self.sale.date

    @property
    def currency(self) -> str:
        return self.sale.currency

    @property
    def account(self) -> str | None:
        return self.sale.account

    @property
    def term(self) -> str:
        return UNKNOWN if self.acquired is None else holding_term(self.acquired, self.sold)

    @property
    def gain(self) -> Decimal | None:
        return None if self.basis is None else money(self.proceeds) - money(self.basis)


def match_fifo(activities: Iterable[Activity]) -> tuple[list[Disposal], list[str]]:
    """Match sells to buys first-in, first-out. Returns disposals and warnings."""
    items = sorted(
        (a for a in activities if a.activity_type in _ORDER and a.symbol),
        key=lambda a: (a.date, _ORDER[a.activity_type]),
    )
    lots: dict[LotKey, deque[Lot]] = defaultdict(deque)
    disposals: list[Disposal] = []
    warnings: list[str] = []

    for a in items:
        t = a.activity_type
        if t is ActivityType.SPLIT:
            if not a.amount:
                warnings.append(f"SPLIT {a.symbol} on {a.date} has no ratio; ignored")
                continue
            for (account, symbol, _), queue in lots.items():
                if account == a.account and symbol == a.symbol:
                    for lot in queue:
                        lot.quantity *= a.amount
            continue

        key = (a.account, a.symbol, a.currency)
        if not a.quantity:
            warnings.append(f"{t} {a.symbol} on {a.date} has no quantity; ignored")
            continue
        if t is ActivityType.BUY:
            lots[key].append(Lot(a.date, a.quantity, buy_cost(a)))
            continue

        # SELL: proceeds are split across lots by quantity in whole cents; the last
        # piece gets the remainder so the pieces add up to the sale exactly.
        total = sell_proceeds(a)
        remaining, unallocated = a.quantity, total
        queue = lots[key]
        while remaining > 0 and queue:
            lot = queue[0]
            qty = min(remaining, lot.quantity)
            basis = lot.take(qty)
            if lot.quantity == 0:
                queue.popleft()
            remaining -= qty
            proceeds = unallocated if remaining == 0 else money(total * qty / a.quantity)
            unallocated -= proceeds
            disposals.append(Disposal(a, qty, lot.acquired, proceeds, basis))
        if remaining > 0:
            where = f" in account {a.account}" if a.account else ""
            matched = a.quantity - remaining
            bought = f"only {fmt_decimal(matched)} shares were" if matched else "no shares were"
            warnings.append(
                f"SELL {fmt_decimal(a.quantity)} {a.symbol} on {a.date}{where}: {bought} "
                f"bought earlier in the converted statements, so {fmt_decimal(remaining)} "
                "shares have no cost basis. Convert earlier statements too, or take the "
                "basis from your 1099-B."
            )
            disposals.append(Disposal(a, remaining, None, unallocated, None))
    return disposals, warnings


def summarize(disposals: Iterable[Disposal]) -> list[str]:
    """Human-readable totals per currency and term."""
    totals: dict[tuple[str, str], list[Decimal]] = defaultdict(lambda: [ZERO, ZERO, ZERO])
    unmatched: dict[str, Decimal] = defaultdict(Decimal)
    for d in disposals:
        if d.basis is None:
            unmatched[d.currency] += money(d.proceeds)
            continue
        t = totals[(d.currency, d.term)]
        t[0] += money(d.proceeds)
        t[1] += money(d.basis)
        t[2] += d.gain

    lines = ["Realized gains (FIFO):"]
    for currency in sorted({c for c, _ in totals} | set(unmatched)):
        net = ZERO
        for term, label in ((SHORT, "Short-term"), (LONG, "Long-term")):
            proceeds, basis, gain = totals.get((currency, term), [ZERO, ZERO, ZERO])
            net += gain
            lines.append(
                f"  {label + ':':<11} proceeds {proceeds:>14,.2f}  cost basis {basis:>14,.2f}"
                f"  gain/loss {gain:>14,.2f} {currency}"
            )
        lines.append(f"  {'Total:':<11} gain/loss {net:,.2f} {currency}")
        if currency in unmatched:
            lines.append(
                f"  Not included: {unmatched[currency]:,.2f} {currency} of proceeds "
                "with unknown cost basis (term 'unknown')."
            )
    lines.append(DISCLAIMER)
    return lines


class GainsExporter(Exporter):
    name = "gains"
    display_name = "Realized gains (FIFO)"
    supports_xlsx = True
    row_noun = "sale lots"
    xlsx_number_formats: ClassVar[Mapping[str, str]] = {
        c: "#,##0.00" for c in ("proceeds", "cost_basis", "gain_loss")
    }

    def format_cell(self, value: Cell) -> str:
        if isinstance(value, Decimal):
            return format(value, "f")  # money is already rounded to cents: keep "2.40"
        return super().format_cell(value)

    def build(self, activities: Iterable[Activity]) -> Table:
        items = list(activities)
        disposals, warnings = match_fifo(items)
        with_account = any(d.account for d in disposals)
        header = [*COLUMNS, "account"] if with_account else list(COLUMNS)
        rows: list[dict[str, Cell]] = []
        for d in disposals:
            row: dict[str, Cell] = {
                "description": f"{fmt_decimal(d.quantity)} sh. {d.symbol}",
                "date_acquired": d.acquired,
                "date_sold": d.sold,
                "proceeds": money(d.proceeds),
                "cost_basis": None if d.basis is None else money(d.basis),
                "gain_loss": d.gain,
                "term": d.term,
            }
            if with_account:
                row["account"] = d.account or ""
            rows.append(row)
        if not any(a.activity_type is ActivityType.SELL for a in items):
            warnings.append("no SELL activities found; there are no realized gains to report")
        result = ExportResult(written=len(rows), warnings=warnings)
        result.summary = summarize(disposals) if disposals else [DISCLAIMER]
        return Table(header, rows, result)
