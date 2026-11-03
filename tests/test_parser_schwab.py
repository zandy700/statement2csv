from __future__ import annotations

import datetime as dt
import warnings
from decimal import Decimal
from pathlib import Path

import pytest

from statement2csv.models import Activity, ActivityType
from statement2csv.parsers import ParserError
from statement2csv.parsers.schwab import SchwabParser

D = Decimal
T = ActivityType


def act(day: int, kind: ActivityType, comment: str, **kw: object) -> Activity:
    """January 2024 USD activity (the fixture statement period)."""
    return Activity(
        date=dt.date(2024, 1, day), activity_type=kind, currency="USD", comment=comment, **kw
    )


# Derived from TRANSACTIONS in tests/fixtures/generate_schwab.py, in printed order.
EXPECTED = [
    act(2, T.DEPOSIT, "WIRED FUNDS RECEIVED", amount=D("25000.00")),
    act(
        3,
        T.BUY,
        "Buy: APPLE INC",
        symbol="AAPL",
        quantity=D("10.5"),
        unit_price=D("185.20"),
        fee=D("4.95"),
        amount=D("1949.55"),
    ),
    act(
        5,
        T.BUY,
        "Buy: VANGUARD TOTAL STOCK MARKET ETF",
        symbol="VTI",
        quantity=D(50),
        unit_price=D("236.12"),
        amount=D("11806.00"),
    ),
    act(
        8,
        T.BUY,
        "Buy: EXAMPLE GLOBAL INFRASTRUCTURE INCOME FUND INSTITUTIONAL CLASS",
        symbol="99999X105",
        quantity=D("125.125"),
        unit_price=D(16),
        fee=D("2.50"),
        amount=D("2004.50"),
    ),
    act(
        10,
        T.SELL,
        "Sell: MICROSOFT CORP",
        symbol="MSFT",
        quantity=D("8.25"),
        unit_price=D("375.40"),
        fee=D("0.07"),
        amount=D("3096.98"),
    ),
    act(16, T.DIVIDEND, "VANGUARD TOTAL STOCK MARKET ETF", symbol="VTI", amount=D("45.67")),
    act(16, T.DIVIDEND, "VANGUARD REAL ESTATE ETF", symbol="VNQ", amount=D("12.34")),
    # first rows after the page break
    act(17, T.DIVIDEND, "NOVARTIS AG SPON ADR", symbol="NVS", amount=D("88.20")),
    act(17, T.TAX, "NOVARTIS AG SPON ADR", symbol="NVS", amount=D("13.23")),
    act(18, T.FEE, "NOVARTIS AG SPON ADR", symbol="NVS", amount=D("1.50")),
    act(
        19,
        T.SELL,
        "Sell: APPLE INC",
        symbol="AAPL",
        quantity=D(4),
        unit_price=D("190.10"),
        fee=D("0.02"),
        amount=D("760.38"),
    ),
    act(22, T.DIVIDEND, "SCHWAB US DIVIDEND EQUITY ETF", symbol="SCHD", amount=D("30.00")),
    act(
        22,
        T.BUY,
        "Reinvested Shares: SCHWAB US DIVIDEND EQUITY ETF",
        symbol="SCHD",
        quantity=D("0.4"),
        unit_price=D(75),
        amount=D("30.00"),
    ),
    act(24, T.WITHDRAWAL, "TFR EXAMPLE BANK NA", amount=D("2500.00")),
    act(25, T.WITHDRAWAL, "WIRED FUNDS DISBURSED", amount=D("1000.00")),
    act(25, T.FEE, "WIRE TRANSFER FEE", amount=D("15.00")),
    act(30, T.INTEREST, "SCHWAB1 INT 12/28-01/29", amount=D("3.21")),
    act(31, T.INTEREST, "BANK INT 010124-013124 SCHWAB BANK", amount=D("5.43")),
]


@pytest.fixture(scope="module")
def parsed() -> tuple[list[Activity], list[warnings.WarningMessage]]:
    path = Path(__file__).parent / "fixtures" / "schwab_statement.pdf"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        activities = SchwabParser().parse(path)
    return activities, caught


def test_parse_matches_expected_activities(parsed) -> None:
    activities, _ = parsed
    assert activities == EXPECTED


def test_activity_count_and_defaults(parsed) -> None:
    activities, _ = parsed
    assert len(activities) == 18
    assert all(a.currency == "USD" and a.account is None for a in activities)


def test_unsupported_journal_row_warns_once(parsed) -> None:
    _, caught = parsed
    messages = [str(w.message) for w in caught]
    assert len(messages) == 1
    assert messages[0].startswith("Schwab: skipping")
    assert "Journaled Shares" in messages[0]


def test_bank_sweep_total_and_summary_rows_are_ignored(parsed) -> None:
    activities, _ = parsed
    assert not any("SWEEP" in (a.comment or "") for a in activities)
    # Total Transactions line, account summary and positions values are not activities.
    amounts = {a.amount for a in activities}
    assert not amounts & {D("146359.69"), D("123456.78"), D("70318.26"), D("3500.00")}
    assert not any(a.symbol == "FCNTX" for a in activities)
    # Only one 5.43 (the interest); the sweep's mirrored (5.43) is dropped.
    assert [a.amount for a in activities].count(D("5.43")) == 1


def test_blank_date_rows_inherit_date_above(parsed) -> None:
    activities, _ = parsed
    tax = next(a for a in activities if a.activity_type is T.TAX)
    assert tax.date == dt.date(2024, 1, 17)  # grouped under the NVS dividend
    wire_fee = next(a for a in activities if a.comment == "WIRE TRANSFER FEE")
    assert wire_fee.date == dt.date(2024, 1, 25)


def test_amount_sign_styles_normalised(parsed) -> None:
    activities, _ = parsed
    by_symbol = {a.symbol: a for a in activities if a.activity_type is T.BUY and a.fee}
    assert by_symbol["AAPL"].amount == D("1949.55")  # parentheses
    assert by_symbol["99999X105"].amount == D("2004.50")  # leading minus + thousands
    msft = next(a for a in activities if a.symbol == "MSFT")
    assert msft.quantity == D("8.25")  # "(8.2500)" share quantity


def test_thousands_separators(parsed) -> None:
    activities, _ = parsed
    assert D("25000.00") in {a.amount for a in activities}
    assert D("11806.00") in {a.amount for a in activities}


def test_cusip_only_symbol_and_wrapped_description(parsed) -> None:
    activities, _ = parsed
    fund = next(a for a in activities if a.symbol == "99999X105")
    assert fund.comment.endswith("INCOME FUND INSTITUTIONAL CLASS")
    assert fund.quantity == D("125.125")


def test_reinvestment_is_dividend_plus_buy(parsed) -> None:
    activities, _ = parsed
    schd = [a for a in activities if a.symbol == "SCHD"]
    assert [a.activity_type for a in schd] == [T.DIVIDEND, T.BUY]
    assert schd[0].date == schd[1].date == dt.date(2024, 1, 22)


def test_rows_continuing_on_next_page_are_parsed(parsed) -> None:
    activities, _ = parsed
    assert any(a.symbol == "NVS" and a.activity_type is T.DIVIDEND for a in activities)
    assert {a.date.year for a in activities} == {2024}


def test_parse_wrong_broker_files_raise(fidelity_pdf: Path, robinhood_csv: Path) -> None:
    with pytest.raises(ParserError, match="not a Charles Schwab"):
        SchwabParser().parse(fidelity_pdf)
    with pytest.raises(ParserError):
        SchwabParser().parse(robinhood_csv)


def test_parse_non_matching_files_raise(tmp_path: Path) -> None:
    fake = tmp_path / "fake.pdf"
    fake.write_text("not a pdf at all")
    with pytest.raises(ParserError):
        SchwabParser().parse(fake)
    with pytest.raises(ParserError):
        SchwabParser().parse(tmp_path / "missing.pdf")
