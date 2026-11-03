"""Wealthfolio activity import CSV. See docs/formats.md#wealthfolio."""

from __future__ import annotations

from collections.abc import Sequence

from statement2csv.exporters.base import Exporter, fmt_decimal
from statement2csv.models import Activity, ActivityType

BASE_COLUMNS = [
    "date",
    "symbol",
    "quantity",
    "activityType",
    "unitPrice",
    "currency",
    "fee",
    "amount",
    "comment",
]


class WealthfolioExporter(Exporter):
    name = "wealthfolio"
    display_name = "Wealthfolio"

    def header(self, activities: Sequence[Activity]) -> list[str]:
        if any(a.account for a in activities):
            return [*BASE_COLUMNS, "account"]
        return list(BASE_COLUMNS)

    def row(self, activity: Activity, header: Sequence[str]) -> dict[str, str]:
        t = activity.activity_type
        if t in (ActivityType.BUY, ActivityType.SELL):
            # A blank amount lets Wealthfolio compute qty x price +/- fee. A broker
            # total is kept as-is (it is already the final cash amount).
            amount = activity.amount
        else:
            amount = activity.cash_amount

        # Cash rows don't need quantity/unit price. Keep them only when the broker
        # gave them (e.g. a per-share dividend).
        row = {
            "date": activity.date.isoformat(),
            "symbol": activity.symbol or "",
            "quantity": fmt_decimal(activity.quantity),
            "activityType": t.value,
            "unitPrice": fmt_decimal(activity.unit_price),
            "currency": activity.currency,
            "fee": fmt_decimal(activity.fee),
            "amount": fmt_decimal(amount),
            "comment": activity.comment or "",
        }
        if t is ActivityType.FEE and activity.amount is None:
            # Fee is the amount here. Don't report it twice.
            row["fee"] = "0"
        if "account" in header:
            row["account"] = activity.account or ""
        return row
