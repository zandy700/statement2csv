"""Ghostfolio activity import CSV. See docs/formats.md#ghostfolio."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from statement2csv.exporters.base import Exporter, fmt_decimal
from statement2csv.models import Activity, ActivityType

# Same header names as upstream test/import/ok/sample.csv.
BASE_COLUMNS = [
    "Date",
    "Code",
    "DataSource",
    "Currency",
    "Price",
    "Quantity",
    "Action",
    "Fee",
    "Note",
]

_CASH_HINT = "update the account cash balance in Ghostfolio instead"
_UNSUPPORTED = {
    ActivityType.DEPOSIT: f"Ghostfolio has no deposit activity; {_CASH_HINT}",
    ActivityType.WITHDRAWAL: f"Ghostfolio has no withdrawal activity; {_CASH_HINT}",
    ActivityType.SPLIT: "Ghostfolio takes splits from market data; no activity needed",
}

ZERO = Decimal(0)
ONE = Decimal(1)


class GhostfolioExporter(Exporter):
    name = "ghostfolio"
    display_name = "Ghostfolio"

    def header(self, activities: Sequence[Activity]) -> list[str]:
        if any(a.account for a in activities):
            return [*BASE_COLUMNS, "Account"]
        return list(BASE_COLUMNS)

    def row(self, activity: Activity, header: Sequence[str]) -> dict[str, str] | str:
        t = activity.activity_type
        if t in _UNSUPPORTED:
            return _UNSUPPORTED[t]

        data_source = ""
        code = activity.symbol or ""
        note = activity.comment or ""
        fee = activity.fee

        if t in (ActivityType.BUY, ActivityType.SELL):
            action = t.value.lower()
            price, quantity = activity.unit_price, activity.quantity
        elif t is ActivityType.DIVIDEND:
            action = "dividend"
            gross = activity.gross_value
            # Per-share form only when it gives the same cash total as ``amount``
            # (e.g. not when amount is net of withholding).
            if activity.quantity and gross is not None and activity.amount in (None, gross):
                price, quantity = activity.unit_price, activity.quantity
            else:
                price, quantity = activity.cash_amount, ONE
        elif t is ActivityType.INTEREST:
            action = "interest"
            data_source = "MANUAL"
            code = code or "Interest"
            price, quantity = activity.amount, ONE
        else:  # FEE, TAX
            action = "fee"
            data_source = "MANUAL"
            code = code or ("Tax" if t is ActivityType.TAX else "Fee")
            price, quantity = ZERO, ZERO
            fee = activity.cash_amount or ZERO
            if t is ActivityType.TAX:
                note = f"Tax: {note}" if note else "Tax"

        row = {
            "Date": activity.date.isoformat(),
            "Code": code,
            "DataSource": data_source,
            "Currency": activity.currency,
            "Price": fmt_decimal(price if price is not None else ZERO),
            "Quantity": fmt_decimal(quantity if quantity is not None else ZERO),
            "Action": action,
            "Fee": fmt_decimal(fee),
            "Note": note,
        }
        if "Account" in header:
            row["Account"] = activity.account or ""
        return row
