from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from statement2csv.models import ActivityType
from statement2csv.parsers._common import (
    cash_sign_matches,
    is_option_trade,
    parse_money,
    parse_us_date,
    reconcile_unit_price,
    resolve_month_day,
    resolve_statement_date,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12", Decimal("12")),
        ("1,234.56", Decimal("1234.56")),
        ("$1,234.56", Decimal("1234.56")),
        ("  $10,000.00  ", Decimal("10000.00")),
        ("+5.5", Decimal("5.5")),
        ("-5.50", Decimal("-5.50")),
        ("(1,234.56)", Decimal("-1234.56")),
        ("($1,234.50)", Decimal("-1234.50")),
        ("1,234.56-", Decimal("-1234.56")),
        ("-$5.00", Decimal("-5.00")),
        ("$-5.00", Decimal("-5.00")),
        ("\u22125.00", Decimal("-5.00")),
        ("0.523164", Decimal("0.523164")),
    ],
)
def test_parse_money_values(text: str, expected: Decimal) -> None:
    assert parse_money(text) == expected


@pytest.mark.parametrize("text", [None, "", "   ", "-", "--", "\u2014", "\u2013", "n/a", "N/A"])
def test_parse_money_blank_markers_are_none(text: str | None) -> None:
    assert parse_money(text) is None


@pytest.mark.parametrize("text", ["abc", "1.2.3", "12a", "$", "(", "1,23x", "5 5x"])
def test_parse_money_invalid_raises(text: str) -> None:
    with pytest.raises(ValueError, match="not a number"):
        parse_money(text)


@pytest.mark.parametrize("text", ["--5", "(-5.00)", "-5.00-"])
def test_parse_money_double_negative_is_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="not a number"):
        parse_money(text)


def test_parse_us_date_four_and_two_digit_years() -> None:
    assert parse_us_date("2/15/2024") == dt.date(2024, 2, 15)
    assert parse_us_date(" 02/15/24 ") == dt.date(2024, 2, 15)


@pytest.mark.parametrize("text", ["2024-02-15", "13/01/2024", "02/30/2024", ""])
def test_parse_us_date_invalid(text: str) -> None:
    with pytest.raises(ValueError, match="MM/DD/YYYY"):
        parse_us_date(text)


def test_resolve_month_day_in_period() -> None:
    start, end = dt.date(2024, 2, 1), dt.date(2024, 2, 29)
    assert resolve_month_day("02/15", start, end) == dt.date(2024, 2, 15)
    assert resolve_month_day("2/1", start, end) == start
    assert resolve_month_day("02/29", start, end) == end


def test_resolve_month_day_period_spanning_year_end() -> None:
    start, end = dt.date(2023, 12, 15), dt.date(2024, 1, 14)
    assert resolve_month_day("12/20", start, end) == dt.date(2023, 12, 20)
    assert resolve_month_day("01/05", start, end) == dt.date(2024, 1, 5)


def test_resolve_month_day_leap_day_only_in_leap_year() -> None:
    assert resolve_month_day("02/29", dt.date(2024, 2, 1), dt.date(2024, 2, 29)) == dt.date(
        2024, 2, 29
    )
    # 2023 has no Feb 29: the candidate must come from the leap year 2024.
    assert resolve_month_day("02/29", dt.date(2023, 12, 1), dt.date(2024, 3, 1)) == dt.date(
        2024, 2, 29
    )


def test_resolve_month_day_outside_period_picks_closest_year() -> None:
    # A settlement date just after the period end (e.g. 02/01 on a Dec 2023 statement).
    start, end = dt.date(2023, 12, 1), dt.date(2023, 12, 31)
    assert resolve_month_day("01/02", start, end) == dt.date(2024, 1, 2)
    # ...and just before the period start.
    assert resolve_month_day("11/30", dt.date(2024, 1, 1), dt.date(2024, 1, 31)) == dt.date(
        2023, 11, 30
    )


def test_resolve_month_day_invalid() -> None:
    with pytest.raises(ValueError):
        resolve_month_day("02/30", dt.date(2024, 2, 1), dt.date(2024, 2, 29))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("$ 5,210.33", Decimal("5210.33")),
        (".50", Decimal("0.50")),
        ("-.50", Decimal("-0.50")),
        ("12,345,678.9", Decimal("12345678.9")),
    ],
)
def test_parse_money_more_valid_forms(text: str, expected: Decimal) -> None:
    assert parse_money(text) == expected


@pytest.mark.parametrize("text", ["12,34", "1,23,4", "1 234.56", "+-5", "5,"])
def test_parse_money_rejects_bad_grouping_and_merged_cells(text: str) -> None:
    # "1 234.56" is what two PDF words merged into one numeric cell look like.
    with pytest.raises(ValueError, match="not a number"):
        parse_money(text)


@pytest.mark.parametrize(
    ("action", "symbol", "security", "expected"),
    [
        ("Sell to Open", "AAPL", "", True),
        ("YOU SOLD OPENING TRANSACTION", "AAPL", "", True),
        ("Buy", "AAPL240119C00190000", "", True),
        ("You Sold", "AAPL", "PUT (AAPL) APPLE INC FEB 16 24 $180 (100 SHS)", True),
        ("You Bought", "QYLD", "GLOBAL X NASDAQ 100 COVERED CALL ETF", False),
        ("Buy", "CPE", "CALLON PETROLEUM CO", False),
        ("Buy", "AAPL", "APPLE INC", False),
    ],
)
def test_is_option_trade(action: str, symbol: str, security: str, expected: bool) -> None:
    assert is_option_trade(action, symbol, security) is expected


D = Decimal
BUY, SELL = ActivityType.BUY, ActivityType.SELL


@pytest.mark.parametrize(
    ("kind", "qty", "price", "fee", "amount", "expected_price", "warns"),
    [
        (BUY, D(10), D("185.20"), D("4.95"), D("1856.95"), D("185.20"), False),  # consistent
        (SELL, D(4), D("190.10"), D("0.02"), D("760.38"), D("190.10"), False),
        (BUY, D(10), D("185.2"), D(0), None, D("185.2"), False),  # no amount: keep price
        (BUY, D(10), None, D(1), D("101"), D(10), False),  # no price: derive it
        (BUY, D(10000), D("98.765"), D(0), D("9876.50"), D("0.98765"), False),  # bond
        (SELL, D(1), D("2.50"), D("0.66"), D("249.34"), D(250), True),  # x100 mismatch
    ],
)
def test_reconcile_unit_price(kind, qty, price, fee, amount, expected_price, warns) -> None:
    unit_price, problem = reconcile_unit_price(kind, qty, price, fee, amount)
    assert unit_price == expected_price
    assert (problem is not None) is warns


def test_reconcile_unit_price_needs_price_or_amount() -> None:
    with pytest.raises(ValueError):
        reconcile_unit_price(BUY, D(1), None, D(0), None)


@pytest.mark.parametrize(
    ("kind", "amount", "expected"),
    [
        (ActivityType.DEPOSIT, D(1), True),
        (ActivityType.DEPOSIT, D(-1), False),
        (ActivityType.WITHDRAWAL, D(-1), True),
        (ActivityType.WITHDRAWAL, D(1), False),
        (ActivityType.DIVIDEND, D(-1), False),
        (ActivityType.TAX, D(-1), True),
        (ActivityType.FEE, D(1), False),
        (ActivityType.INTEREST, D(1), True),
    ],
)
def test_cash_sign_matches(kind: ActivityType, amount: Decimal, expected: bool) -> None:
    assert cash_sign_matches(kind, amount) is expected


def test_resolve_statement_date_keeps_explicit_year() -> None:
    start, end = dt.date(2024, 1, 1), dt.date(2024, 1, 31)
    assert resolve_statement_date("12/29/2022", start, end) == dt.date(2022, 12, 29)
    assert resolve_statement_date("12/29/22", start, end) == dt.date(2022, 12, 29)
    assert resolve_statement_date("01/15", start, end) == dt.date(2024, 1, 15)
