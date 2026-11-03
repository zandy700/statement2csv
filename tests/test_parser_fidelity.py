from __future__ import annotations

import datetime as dt
import warnings
from decimal import Decimal
from pathlib import Path

import pytest

from statement2csv.models import Activity, ActivityType
from statement2csv.parsers import ParserError
from statement2csv.parsers.fidelity import FidelityParser

D = Decimal
T = ActivityType


def act(day: int, kind: ActivityType, comment: str, **kw: object) -> Activity:
    """February 2024 USD activity (the fixture statement period)."""
    return Activity(
        date=dt.date(2024, 2, day), activity_type=kind, currency="USD", comment=comment, **kw
    )


# Derived from the source data in tests/fixtures/generate_fidelity.py, in document order:
# trades (page 2, then page 3 after the break), income, deposits, withdrawals, fees.
EXPECTED = [
    act(
        2,
        T.BUY,
        "You Bought: APPLE INC",
        symbol="AAPL",
        quantity=D("10.5"),
        unit_price=D("185.20"),
        fee=D("4.95"),
        amount=D("1949.55"),
    ),
    act(
        5,
        T.BUY,
        "You Bought: VANGUARD TOTAL STOCK MARKET ETF",
        symbol="VTI",
        quantity=D(50),
        unit_price=D("236.12"),
        amount=D("11806.00"),
    ),
    act(
        7,
        T.BUY,
        "You Bought: EXAMPLE GLOBAL INFRASTRUCTURE INCOME FUND CL I",
        symbol="99999X105",
        quantity=D("125.125"),
        unit_price=D(16),
        amount=D("2002.00"),
    ),
    # first row after the page break
    act(
        9,
        T.SELL,
        "You Sold: MICROSOFT CORP",
        symbol="MSFT",
        quantity=D("8.25"),
        unit_price=D("375.40"),
        fee=D("0.07"),
        amount=D("3096.98"),
    ),
    act(
        20,
        T.SELL,
        "You Sold: APPLE INC",
        symbol="AAPL",
        quantity=D(4),
        unit_price=D("190.10"),
        fee=D("0.02"),
        amount=D("760.38"),
    ),
    act(
        22,
        T.BUY,
        "You Bought: NVIDIA CORP",
        symbol="NVDA",
        quantity=D("12.345"),
        unit_price=D(650),
        amount=D("8024.25"),
    ),
    act(
        15,
        T.DIVIDEND,
        "Dividend Received: VANGUARD TOTAL STOCK MARKET ETF",
        symbol="VTI",
        amount=D("45.67"),
    ),
    act(16, T.DIVIDEND, "Dividend Received: NOVARTIS AG SPON ADR", symbol="NVS", amount=D("88.20")),
    act(16, T.TAX, "Foreign Tax Paid: NOVARTIS AG SPON ADR", symbol="NVS", amount=D("13.23")),
    act(
        21,
        T.DIVIDEND,
        "Long-Term Cap Gain: EXAMPLE GLOBAL INFRASTRUCTURE INCOME FUND CL I",
        symbol="99999X105",
        amount=D("12.34"),
    ),
    act(
        26,
        T.DIVIDEND,
        "Dividend Received: SCHWAB US DIVIDEND EQUITY ETF",
        symbol="SCHD",
        amount=D("42.34"),
    ),
    act(
        26,
        T.BUY,
        "Reinvestment: SCHWAB US DIVIDEND EQUITY ETF",
        symbol="SCHD",
        quantity=D("0.552"),
        unit_price=D("76.70"),
        amount=D("42.34"),
    ),
    act(
        29,
        T.INTEREST,
        "Interest Earned: UNITED STATES TREAS BILLS ZERO CPN",
        symbol="912797ZZ1",
        amount=D("125.00"),
    ),
    act(29, T.INTEREST, "Interest Earned", amount=D("3.21")),
    act(1, T.DEPOSIT, "Electronic Funds Transfer Received", amount=D("25000.00")),
    act(12, T.DEPOSIT, "Check Received (1001)", amount=D("1500.00")),
    act(23, T.WITHDRAWAL, "Electronic Funds Transfer Paid", amount=D("2500.00")),
    act(27, T.WITHDRAWAL, "Wire Transfer to Bank", amount=D("1000.00")),
    act(27, T.FEE, "Wire Transfer Fee", amount=D("15.00")),
]


@pytest.fixture(scope="module")
def parsed() -> tuple[list[Activity], list[warnings.WarningMessage]]:
    path = Path(__file__).parent / "fixtures" / "fidelity_statement.pdf"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        activities = FidelityParser().parse(path)
    return activities, caught


def test_parse_matches_expected_activities(parsed) -> None:
    activities, _ = parsed
    assert activities == EXPECTED


def test_activity_count_and_defaults(parsed) -> None:
    activities, _ = parsed
    assert len(activities) == 19
    assert all(a.currency == "USD" and a.account is None for a in activities)


def test_only_unsupported_other_activity_warns(parsed) -> None:
    _, caught = parsed
    messages = [str(w.message) for w in caught]
    assert len(messages) == 1
    assert "unsupported transaction" in messages[0]
    assert "Transfer of Assets" in messages[0]


def test_totals_summary_holdings_and_core_fund_rows_ignored(parsed) -> None:
    activities, _ = parsed
    # Core Fund Activity (SPAXX sweep, incl. a 25,000 buy and 11,806 sell) must not leak.
    assert not any("MONEY MARKET" in (a.comment or "") for a in activities)
    assert not any(a.symbol == "SPAXX" for a in activities)
    # Page 1 summary/holdings/estimated cash flow numbers never become activities.
    amounts = {a.amount for a in activities}
    assert not amounts & {D("146359.69"), D("3500.00"), D("316.76"), D("322.57"), D("13640.58")}
    assert not any(a.symbol == "AAPL" and a.quantity == D("16.5") for a in activities)


def test_decimal_quantity_and_unit_price(parsed) -> None:
    activities, _ = parsed
    nvda = next(a for a in activities if a.symbol == "NVDA")
    assert nvda.quantity == D("12.345") and nvda.unit_price == D(650)
    # parenthesised negative amount "(8,024.25)" -> non-negative magnitude
    assert nvda.amount == D("8024.25")


def test_sells_have_positive_quantity_and_amount(parsed) -> None:
    activities, _ = parsed
    sells = [a for a in activities if a.activity_type is T.SELL]
    assert [(a.symbol, a.quantity, a.amount) for a in sells] == [
        ("MSFT", D("8.25"), D("3096.98")),
        ("AAPL", D(4), D("760.38")),
    ]


def test_thousands_separators(parsed) -> None:
    activities, _ = parsed
    assert max(a.amount for a in activities) == D("25000.00")
    assert D("11806.00") in {a.amount for a in activities}


def test_year_inferred_from_period_including_leap_day(parsed) -> None:
    activities, _ = parsed
    assert {a.date.year for a in activities} == {2024}
    assert dt.date(2024, 2, 29) in {a.date for a in activities}
    assert all(dt.date(2024, 2, 1) <= a.date <= dt.date(2024, 2, 29) for a in activities)


def test_reinvestment_is_dividend_plus_buy(parsed) -> None:
    activities, _ = parsed
    schd = [a for a in activities if a.symbol == "SCHD"]
    assert [a.activity_type for a in schd] == [T.DIVIDEND, T.BUY]
    # The printed amount wins over quantity x price (0.552 x 76.70 = 42.3384).
    assert schd[0].amount == schd[1].amount == D("42.34")


def test_cusip_only_symbols(parsed) -> None:
    activities, _ = parsed
    assert {a.symbol for a in activities if a.symbol and a.symbol[0].isdigit()} == {
        "99999X105",
        "912797ZZ1",
    }


def test_wrapped_security_name_is_joined_in_comment(parsed) -> None:
    activities, _ = parsed
    vti = next(a for a in activities if a.symbol == "VTI" and a.activity_type is T.BUY)
    assert vti.comment == "You Bought: VANGUARD TOTAL STOCK MARKET ETF"


def test_blank_symbol_interest_has_no_symbol(parsed) -> None:
    activities, _ = parsed
    blank = [a for a in activities if a.activity_type is T.INTEREST and a.symbol is None]
    assert [a.amount for a in blank] == [D("3.21")]


def test_parse_is_deterministic(fidelity_pdf: Path, parsed) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert FidelityParser().parse(fidelity_pdf) == parsed[0]


def test_parse_wrong_broker_files_raise(schwab_pdf: Path, robinhood_csv: Path) -> None:
    with pytest.raises(ParserError, match="not a Fidelity"):
        FidelityParser().parse(schwab_pdf)
    with pytest.raises(ParserError):
        FidelityParser().parse(robinhood_csv)


def test_parse_non_matching_files_raise(tmp_path: Path) -> None:
    fake = tmp_path / "fake.pdf"
    fake.write_text("not a pdf at all")
    with pytest.raises(ParserError):
        FidelityParser().parse(fake)
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    with pytest.raises(ParserError):
        FidelityParser().parse(empty)
    with pytest.raises(ParserError):
        FidelityParser().parse(tmp_path / "missing.pdf")
