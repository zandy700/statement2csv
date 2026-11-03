from __future__ import annotations

import datetime as dt
import io
from decimal import Decimal

import pytest

from statement2csv.exporters import GhostfolioExporter, WealthfolioExporter, fmt_decimal
from statement2csv.models import Activity, ActivityType

D = Decimal


def sample_activities() -> list[Activity]:
    return [
        Activity(
            date=dt.date(2024, 1, 15),
            symbol="AAPL",
            activity_type=ActivityType.BUY,
            quantity=D(10),
            unit_price=D("185.50"),
            fee=D("4.95"),
            currency="usd",
            comment="Initial purchase",
        ),
        Activity(
            date=dt.date(2024, 2, 1),
            symbol="AAPL",
            activity_type=ActivityType.DIVIDEND,
            amount=D("2.40"),
            currency="USD",
        ),
        Activity(
            date=dt.date(2024, 3, 1),
            activity_type=ActivityType.DEPOSIT,
            amount=D(5000),
            currency="USD",
        ),
        Activity(
            date=dt.date(2024, 4, 1),
            activity_type=ActivityType.INTEREST,
            amount=D("12.50"),
            currency="USD",
        ),
        Activity(
            date=dt.date(2024, 4, 15),
            activity_type=ActivityType.FEE,
            amount=D(25),
            currency="USD",
            comment="Account fee",
        ),
        Activity(
            date=dt.date(2024, 5, 15),
            symbol="NVDA",
            activity_type=ActivityType.SPLIT,
            amount=D(3),
            currency="USD",
        ),
        Activity(
            date=dt.date(2024, 6, 1),
            symbol="AAPL",
            activity_type=ActivityType.TAX,
            amount=D("0.36"),
            currency="USD",
            comment="Withholding",
        ),
    ]


def export(exporter, activities):
    buf = io.StringIO()
    result = exporter.export(activities, buf)
    return buf.getvalue(), result


def test_wealthfolio_export() -> None:
    text, result = export(WealthfolioExporter(), sample_activities())
    assert result.written == 7
    assert not result.skipped
    assert text == (
        "date,symbol,quantity,activityType,unitPrice,currency,fee,amount,comment\n"
        "2024-01-15,AAPL,10,BUY,185.5,USD,4.95,,Initial purchase\n"
        "2024-02-01,AAPL,,DIVIDEND,,USD,0,2.4,\n"
        "2024-03-01,,,DEPOSIT,,USD,0,5000,\n"
        "2024-04-01,,,INTEREST,,USD,0,12.5,\n"
        "2024-04-15,,,FEE,,USD,0,25,Account fee\n"
        "2024-05-15,NVDA,,SPLIT,,USD,0,3,\n"
        "2024-06-01,AAPL,,TAX,,USD,0,0.36,Withholding\n"
    )


def test_ghostfolio_export() -> None:
    text, result = export(GhostfolioExporter(), sample_activities())
    assert result.written == 5
    assert sorted(s.activity.activity_type for s in result.skipped) == ["DEPOSIT", "SPLIT"]
    assert text == (
        "Date,Code,DataSource,Currency,Price,Quantity,Action,Fee,Note\n"
        "2024-01-15,AAPL,,USD,185.5,10,buy,4.95,Initial purchase\n"
        "2024-02-01,AAPL,,USD,2.4,1,dividend,0,\n"
        "2024-04-01,Interest,MANUAL,USD,12.5,1,interest,0,\n"
        "2024-04-15,Fee,MANUAL,USD,0,0,fee,25,Account fee\n"
        "2024-06-01,AAPL,MANUAL,USD,0,0,fee,0.36,Tax: Withholding\n"
    )


def test_account_column_added_only_when_present() -> None:
    activity = Activity(
        date=dt.date(2024, 1, 1),
        activity_type=ActivityType.INTEREST,
        amount=D(1),
        currency="EUR",
        account="Broker EUR",
    )
    wf, _ = export(WealthfolioExporter(), [activity])
    gf, _ = export(GhostfolioExporter(), [activity])
    assert wf.splitlines()[0].endswith(",account")
    assert wf.splitlines()[1].endswith(",Broker EUR")
    assert gf.splitlines()[0].endswith(",Account")


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, ""), (D("1.2300"), "1.23"), (D("1E+3"), "1000"), (D("0.00"), "0"), (D(5), "5")],
)
def test_fmt_decimal(value, expected) -> None:
    assert fmt_decimal(value) == expected


def test_activity_rejects_negative_and_missing_fields() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        Activity(date=dt.date(2024, 1, 1), activity_type="DEPOSIT", amount=-1, currency="USD")
    with pytest.raises(ValueError, match="missing"):
        Activity(date=dt.date(2024, 1, 1), activity_type="BUY", symbol="X", currency="USD")


def test_trade_with_broker_total_and_fee_only_fee_and_per_share_dividend() -> None:
    activities = [
        Activity(
            date=dt.date(2024, 1, 2),
            symbol="AAPL",
            activity_type=ActivityType.BUY,
            quantity=D(10),
            unit_price=D("185.20"),
            fee=D("4.95"),
            amount=D("1856.95"),
            currency="USD",
        ),
        Activity(
            date=dt.date(2024, 1, 3),
            activity_type=ActivityType.FEE,
            fee=D("2.50"),
            currency="USD",
        ),
        Activity(
            date=dt.date(2024, 1, 4),
            symbol="MSFT",
            activity_type=ActivityType.DIVIDEND,
            quantity=D(5),
            unit_price=D("0.62"),
            currency="USD",
        ),
    ]
    wf, _ = export(WealthfolioExporter(), activities)
    assert wf.splitlines()[1:] == [
        # Broker total kept as the final amount (already includes the fee).
        "2024-01-02,AAPL,10,BUY,185.2,USD,4.95,1856.95,",
        # Fee-only FEE: the fee becomes the amount and isn't reported twice.
        "2024-01-03,,,FEE,,USD,0,2.5,",
        # Per-share dividend: amount derived from quantity x price.
        "2024-01-04,MSFT,5,DIVIDEND,0.62,USD,0,3.1,",
    ]
    gf, _ = export(GhostfolioExporter(), activities)
    assert gf.splitlines()[1:] == [
        "2024-01-02,AAPL,,USD,185.2,10,buy,4.95,",
        "2024-01-03,Fee,MANUAL,USD,0,0,fee,2.5,",
        "2024-01-04,MSFT,,USD,0.62,5,dividend,0,",
    ]


def test_same_day_order_is_preserved() -> None:
    buy = Activity(
        date=dt.date(2024, 3, 5),
        symbol="AAPL",
        activity_type=ActivityType.BUY,
        quantity=D(5),
        unit_price=D(200),
        currency="USD",
    )
    sell = Activity(
        date=dt.date(2024, 3, 5),
        symbol="AAPL",
        activity_type=ActivityType.SELL,
        quantity=D(5),
        unit_price=D(210),
        currency="USD",
    )
    earlier = Activity(
        date=dt.date(2024, 3, 1), activity_type=ActivityType.DEPOSIT, amount=D(1), currency="USD"
    )
    text, _ = export(WealthfolioExporter(), [buy, sell, earlier])
    assert [line.split(",")[3] for line in text.splitlines()[1:]] == ["DEPOSIT", "BUY", "SELL"]
