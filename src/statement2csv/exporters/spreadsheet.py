"""Universal, human-friendly CSV (or XLSX) for Excel, Google Sheets and Numbers.

See docs/formats.md#spreadsheet. One row per activity, every activity type kept.

Sign convention (unlike the import formats, which are all positive): ``amount`` is the
signed cash effect on the account (negative = money out) and ``quantity`` is the signed
change in shares (negative = shares out). Quantity and price are filled only on buys
and sells. Summing ``amount`` gives the net cash flow; summing ``quantity`` per symbol
gives the net shares bought (splits are not applied).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import ClassVar

from statement2csv.exporters.base import Cell, Exporter, fmt_decimal
from statement2csv.models import TRADE_TYPES, Activity, ActivityType

COLUMNS = [
    "date",
    "broker",
    "account",
    "type",
    "symbol",
    "description",
    "quantity",
    "price",
    "amount",
    "fees",
    "currency",
]

#: Activity types that take cash out of the account.
_CASH_OUT = frozenset(
    {ActivityType.BUY, ActivityType.WITHDRAWAL, ActivityType.FEE, ActivityType.TAX}
)


def signed_amount(activity: Activity) -> Decimal | None:
    """Cash effect of ``activity``: positive in, negative out, ``None`` if not cash."""
    t = activity.activity_type
    if t is ActivityType.SPLIT:
        return None  # amount is the split ratio, not cash
    amount = activity.amount
    if amount is None and activity.gross_value is not None:
        # BUY: total paid = qty x price + fee. SELL: net proceeds = qty x price - fee.
        if t is ActivityType.BUY:
            amount = activity.gross_value + activity.fee
        elif t is ActivityType.SELL:
            amount = activity.gross_value - activity.fee
    if amount is None:
        amount = activity.cash_amount
    if amount is None:
        return None
    return -amount if t in _CASH_OUT else amount


def split_description(ratio: Decimal) -> str:
    """``2`` -> ``2-for-1 split``, ``1/3`` -> ``1-for-3 reverse split``."""
    places = Decimal("1e-6")
    if ratio >= 1:
        return f"{fmt_decimal(ratio.quantize(places))}-for-1 split"
    return f"1-for-{fmt_decimal((1 / ratio).quantize(places))} reverse split"


class SpreadsheetExporter(Exporter):
    name = "spreadsheet"
    display_name = "Spreadsheet"
    aliases = ("csv",)
    supports_xlsx = True
    xlsx_number_formats: ClassVar[Mapping[str, str]] = {"amount": "#,##0.00", "fees": "#,##0.00"}

    def header(self, activities: Sequence[Activity]) -> list[str]:
        return list(COLUMNS)

    def row(self, activity: Activity, header: Sequence[str]) -> dict[str, Cell]:
        t = activity.activity_type
        description = activity.comment or ""
        fees = activity.fee
        quantity = price = None
        if t in TRADE_TYPES:
            quantity, price = activity.quantity, activity.unit_price
            if t is ActivityType.SELL and quantity is not None:
                quantity = -quantity
        elif not description:
            # Keep per-share details (e.g. of a dividend) without putting a non-trade
            # quantity in the column people sum to get positions.
            if t is ActivityType.SPLIT and activity.amount:
                description = split_description(activity.amount)
            elif activity.quantity is not None and activity.unit_price is not None:
                description = (
                    f"{fmt_decimal(activity.quantity)} shares x {fmt_decimal(activity.unit_price)}"
                )
        if t is ActivityType.FEE:
            # The fee itself, so the fees column totals every fee paid.
            fees = activity.cash_amount or Decimal(0)
        return {
            "date": activity.date,
            "broker": self.broker or "",
            "account": activity.account or "",
            "type": t.value.title(),
            "symbol": activity.symbol or "",
            "description": description,
            "quantity": quantity,
            "price": price,
            "amount": signed_amount(activity),
            "fees": fees,
            "currency": activity.currency,
        }
