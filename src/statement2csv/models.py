"""Normalized, broker-independent representation of portfolio activities.

Conventions (parsers must follow them, exporters rely on them):

* All monetary values and quantities are ``Decimal`` and **non-negative**. The
  direction (cash in/out, shares in/out) is given by ``activity_type``.
* ``currency`` is the ISO 4217 code of the activity (the currency ``unit_price``,
  ``amount`` and ``fee`` are expressed in).
* ``amount`` is the final cash total of the activity, fees and taxes included:
  - BUY: total paid. SELL: net proceeds. If the statement doesn't show it, leave it
    ``None`` and exporters derive what they need from quantity x unit_price.
  - DIVIDEND / INTEREST / DEPOSIT / WITHDRAWAL / FEE / TAX: the cash amount (required).
  - SPLIT: the split ratio, e.g. ``Decimal(2)`` for a 2-for-1 split (Wealthfolio
    convention).
* ``fee`` is the commission/fee charged on the activity (``0`` if none).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class ActivityType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    INTEREST = "INTEREST"
    FEE = "FEE"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    SPLIT = "SPLIT"
    TAX = "TAX"


#: Types that need a symbol, a quantity and a unit price.
TRADE_TYPES = frozenset({ActivityType.BUY, ActivityType.SELL})
#: Types whose cash value lives in ``amount``.
CASH_TYPES = frozenset(
    {
        ActivityType.DIVIDEND,
        ActivityType.INTEREST,
        ActivityType.FEE,
        ActivityType.DEPOSIT,
        ActivityType.WITHDRAWAL,
        ActivityType.TAX,
    }
)

_DECIMAL_FIELDS = ("quantity", "unit_price", "amount", "fee")


def to_decimal(value: object) -> Decimal:
    """Convert ``value`` to ``Decimal`` without going through binary floats."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("bool is not a valid numeric value")
    if isinstance(value, int | float | str):
        try:
            return Decimal(str(value).strip())
        except InvalidOperation as exc:
            raise ValueError(f"not a valid number: {value!r}") from exc
    raise TypeError(f"cannot convert {type(value).__name__} to Decimal")


@dataclass(kw_only=True)
class Activity:
    date: dt.date
    symbol: str | None = None
    activity_type: ActivityType
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None
    fee: Decimal = field(default_factory=Decimal)
    currency: str
    account: str | None = None
    comment: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.date, dt.datetime):
            self.date = self.date.date()
        if not isinstance(self.date, dt.date):
            raise TypeError(f"date must be a datetime.date, got {type(self.date).__name__}")

        self.activity_type = ActivityType(self.activity_type)

        currency = (self.currency or "").strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError(f"currency must be a 3-letter ISO 4217 code, got {self.currency!r}")
        self.currency = currency

        if self.fee is None:
            self.fee = Decimal(0)
        for name in _DECIMAL_FIELDS:
            value = getattr(self, name)
            if value is None:
                continue
            value = to_decimal(value)
            if not value.is_finite():
                raise ValueError(f"{name} must be finite, got {value}")
            if value < 0:
                raise ValueError(
                    f"{name} must be non-negative (direction comes from activity_type), got {value}"
                )
            setattr(self, name, value)

        self.symbol = (self.symbol or "").strip() or None
        self.account = (self.account or "").strip() or None
        self.comment = (self.comment or "").strip() or None

        self._validate_required_fields()

    def _validate_required_fields(self) -> None:
        t = self.activity_type
        missing: list[str] = []
        if t in TRADE_TYPES:
            missing = [n for n in ("symbol", "quantity", "unit_price") if getattr(self, n) is None]
        elif t is ActivityType.SPLIT:
            missing = [n for n in ("symbol", "amount") if getattr(self, n) is None]
        elif t is ActivityType.DIVIDEND:
            if self.symbol is None:
                missing.append("symbol")
            if self.amount is None and (self.quantity is None or self.unit_price is None):
                missing.append("amount (or quantity and unit_price)")
        elif t is ActivityType.FEE:
            if self.amount is None and not self.fee:
                missing.append("amount (or fee)")
        elif t in CASH_TYPES and self.amount is None:
            missing.append("amount")
        if missing:
            raise ValueError(f"{t} activity on {self.date} is missing: {', '.join(missing)}")

    @property
    def gross_value(self) -> Decimal | None:
        """quantity x unit_price, if both are known."""
        if self.quantity is None or self.unit_price is None:
            return None
        return self.quantity * self.unit_price

    @property
    def cash_amount(self) -> Decimal | None:
        """Best-known cash value: ``amount``, else derived from quantity x unit_price."""
        if self.amount is not None:
            return self.amount
        if self.activity_type is ActivityType.FEE:
            return self.fee
        return self.gross_value
