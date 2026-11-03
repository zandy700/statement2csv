from __future__ import annotations

import datetime as dt
import warnings
from decimal import Decimal
from pathlib import Path

import pytest

from statement2csv.models import Activity, ActivityType
from statement2csv.parsers import ParserError
from statement2csv.parsers.robinhood import RobinhoodParser

D = Decimal
T = ActivityType

HEADER = (
    '"Activity Date","Process Date","Settle Date","Instrument","Description",'
    '"Trans Code","Quantity","Price","Amount"'
)


def act(date: str, kind: ActivityType, comment: str | None, **kw: object) -> Activity:
    m, d, y = (int(p) for p in date.split("/"))
    return Activity(
        date=dt.date(y, m, d), activity_type=kind, currency="USD", comment=comment, **kw
    )


# Derived from tests/fixtures/robinhood_activity.csv, in file order (newest first).
# The parser returns them oldest first (reversed).
# Skipped (warn): the NVDA SPL row (no ratio in its description) and the SPY BTO option.
EXPECTED = [
    act("5/1/2024", T.DEPOSIT, "Gold Deposit Boost Payment", amount=D("30.00")),
    act("4/30/2024", T.INTEREST, "Interest Payment", amount=D("12.34")),
    act(
        "4/11/2024",
        T.DIVIDEND,
        "Taiwan Semiconductor Manufacturing",
        symbol="TSM",
        amount=D("6.61"),
    ),
    act("4/11/2024", T.TAX, "Dividend Tax Withholding", symbol="TSM", amount=D("1.39")),
    act("4/11/2024", T.FEE, "ADR Fee", symbol="TSM", amount=D("0.15")),
    act("4/8/2024", T.INTEREST, "Stock Lending Income", amount=D("0.87")),
    act("3/28/2024", T.FEE, "Gold Subscription Fee", amount=D("5.00")),
    # Sell: fee = round(20 x 425.20, 2) - 8503.79 = 8504.00 - 8503.79
    act(
        "3/22/2024",
        T.SELL,
        "Microsoft",
        symbol="MSFT",
        quantity=D(20),
        unit_price=D("425.20"),
        fee=D("0.21"),
        amount=D("8503.79"),
    ),
    act("3/15/2024", T.WITHDRAWAL, "ACH Withdrawal", amount=D("2500.00")),
    act(
        "3/14/2024",
        T.DIVIDEND,
        "Cash Div: R/D 2024-02-15 P/D 2024-03-14 - 20 shares at 0.75",
        symbol="MSFT",
        amount=D("15.00"),
    ),
    # Sell: 30 x 182.31 = 5469.30 - 5469.18
    act(
        "2/20/2024",
        T.SELL,
        "Apple",
        symbol="AAPL",
        quantity=D(30),
        unit_price=D("182.31"),
        fee=D("0.12"),
        amount=D("5469.18"),
    ),
    act(
        "2/15/2024",
        T.DIVIDEND,
        "Cash Div: R/D 2024-02-12 P/D 2024-02-15 - 40 shares at 0.24",
        symbol="AAPL",
        amount=D("9.60"),
    ),
    act(
        "2/2/2024",
        T.BUY,
        "Vanguard S&P 500 ETF",
        symbol="VOO",
        quantity=D("0.523164"),
        unit_price=D("448.05"),
        amount=D("234.40"),
    ),
    act(
        "1/16/2024",
        T.BUY,
        "SPDR S&P 500 ETF Trust",
        symbol="SPY",
        quantity=D(25),
        unit_price=D("472.65"),
        amount=D("11816.25"),
    ),
    act(
        "1/12/2024",
        T.BUY,
        "Microsoft",
        symbol="MSFT",
        quantity=D(20),
        unit_price=D("388.47"),
        amount=D("7769.40"),
    ),
    act(
        "1/10/2024",
        T.BUY,
        "Apple",
        symbol="AAPL",
        quantity=D(40),
        unit_price=D("185.50"),
        amount=D("7420.00"),
    ),
    act("1/8/2024", T.DEPOSIT, "ACH Deposit", amount=D("30000.00")),
]


def parse_with_warnings(path: Path) -> tuple[list[Activity], list[str]]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        activities = RobinhoodParser().parse(path)
    return activities, [str(w.message) for w in caught]


def write_csv(tmp_path: Path, *rows: str, header: str = HEADER, newline: str = "\n") -> Path:
    path = tmp_path / "activity.csv"
    path.write_bytes(newline.join([header, *rows, ""]).encode("utf-8"))
    return path


def row(
    code: str,
    amount: str = "",
    *,
    symbol: str = "",
    desc: str = "",
    qty: str = "",
    price: str = "",
    date: str = "3/1/2024",
) -> str:
    cells = [date, date, date, symbol, desc, code, qty, price, amount]
    return ",".join(f'"{c}"' for c in cells)


def parse_one(tmp_path: Path, *rows: str) -> tuple[list[Activity], list[str]]:
    return parse_with_warnings(write_csv(tmp_path, *rows))


# --- fixture file --------------------------------------------------------------------


def test_fixture_matches_expected_activities(robinhood_csv: Path) -> None:
    activities, _ = parse_with_warnings(robinhood_csv)
    assert activities == EXPECTED[::-1]


def test_fixture_warns_for_split_without_ratio_and_option(robinhood_csv: Path) -> None:
    _, messages = parse_with_warnings(robinhood_csv)
    assert len(messages) == 2
    split, option = messages
    assert "6/10/2024" in split and "SPL" in split and "NVDA" in split
    assert "split ratio" in split
    assert "3/27/2024" in option and "BTO" in option and "options" in option


def test_disclaimer_and_blank_rows_ignored(robinhood_csv: Path) -> None:
    activities, messages = parse_with_warnings(robinhood_csv)
    assert not any("informational" in (a.comment or "") for a in activities)
    assert not any("informational" in m for m in messages)
    assert len(activities) == 17


def test_multiline_description_keeps_first_line_only(robinhood_csv: Path) -> None:
    activities, _ = parse_with_warnings(robinhood_csv)
    assert all(
        "\n" not in (a.comment or "") and "CUSIP" not in (a.comment or "") for a in activities
    )
    # DTAX/AFEE descriptions put the label first, the company name second.
    assert next(a for a in activities if a.activity_type is T.TAX).comment == (
        "Dividend Tax Withholding"
    )


def test_fractional_quantity_and_thousands_amounts(robinhood_csv: Path) -> None:
    activities, _ = parse_with_warnings(robinhood_csv)
    voo = next(a for a in activities if a.symbol == "VOO")
    assert voo.quantity == D("0.523164")
    assert D("30000.00") in {a.amount for a in activities}  # "$30,000.00"
    assert D("11816.25") in {a.amount for a in activities}  # "($11,816.25)"


def test_sell_fee_derived_buy_fee_zero(robinhood_csv: Path) -> None:
    activities, _ = parse_with_warnings(robinhood_csv)
    fees = {(a.activity_type, a.symbol): a.fee for a in activities if a.symbol in ("MSFT", "AAPL")}
    assert fees[(T.SELL, "MSFT")] == D("0.21")
    assert all(f == 0 for (t, _), f in fees.items() if t is T.BUY)


def test_large_sell_gap_is_not_booked_as_fee(tmp_path: Path) -> None:
    # 1000 x $100.00 = $100,000.00; a $900 gap is far above SEC/TAF fee levels.
    activities, _ = parse_one(
        tmp_path, row("Sell", "$99,100.00", symbol="XYZ", qty="1000", price="$100.00")
    )
    assert activities[0].fee == 0
    assert activities[0].amount == D("99100.00")
    # A realistic regulatory fee is still derived: $2.78 SEC + $0.17 TAF.
    activities, _ = parse_one(
        tmp_path, row("Sell", "$99,997.05", symbol="XYZ", qty="1000", price="$100.00")
    )
    assert activities[0].fee == D("2.95")


def test_dividend_is_not_reinvestment_buy(robinhood_csv: Path) -> None:
    activities, _ = parse_with_warnings(robinhood_csv)
    assert [a.activity_type for a in activities if a.symbol == "MSFT"] == [
        T.BUY,
        T.DIVIDEND,
        T.SELL,
    ]


def test_same_day_rows_come_out_in_chronological_order(tmp_path: Path) -> None:
    # Newest first in the export: the sell was after the buy.
    activities, _ = parse_one(
        tmp_path,
        row("Sell", "$1,000.00", symbol="AAPL", qty="5", price="$200.00", date="3/5/2024"),
        row("Buy", "($1,000.00)", symbol="AAPL", qty="5", price="$200.00", date="3/5/2024"),
    )
    assert [a.activity_type for a in activities] == [T.BUY, T.SELL]


# --- wrong / bad input ---------------------------------------------------------------


def test_parse_wrong_broker_files_raise(fidelity_pdf: Path, schwab_pdf: Path) -> None:
    for pdf in (fidelity_pdf, schwab_pdf):
        with pytest.raises(ParserError):
            RobinhoodParser().parse(pdf)


def test_parse_non_matching_files_raise(tmp_path: Path) -> None:
    other = tmp_path / "other.csv"
    other.write_text("Date,Code,DataSource,Currency,Price,Quantity,Action,Fee,Note\n")
    with pytest.raises(ParserError, match="not a Robinhood"):
        RobinhoodParser().parse(other)
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    with pytest.raises(ParserError, match="empty"):
        RobinhoodParser().parse(empty)
    with pytest.raises(ParserError):
        RobinhoodParser().parse(tmp_path / "missing.csv")


@pytest.mark.parametrize("column", ["Activity Date", "Trans Code", "Amount", "Instrument"])
def test_missing_required_column_raises(tmp_path: Path, column: str) -> None:
    header = HEADER.replace(f'"{column}",', "").replace(f',"{column}"', "")
    path = write_csv(tmp_path, header=header)
    with pytest.raises(ParserError, match=f"missing column.*{column}"):
        RobinhoodParser().parse(path)


@pytest.mark.parametrize("amount", ["$12.3.4", "twelve", "$1,2x", "$12,34"])
def test_malformed_amount_skips_row_with_warning(tmp_path: Path, amount: str) -> None:
    activities, messages = parse_one(tmp_path, row("INT", amount), row("INT", "$1.00"))
    assert [a.amount for a in activities] == [D("1.00")]  # the good row survives
    assert len(messages) == 1
    assert "invalid Amount" in messages[0] and "row 2" in messages[0]
    assert "skipped" in messages[0]


def test_malformed_date_and_quantity_skip_row_with_warning(tmp_path: Path) -> None:
    activities, messages = parse_one(tmp_path, row("INT", "$1.00", date="2024-03-01"))
    assert activities == []
    assert len(messages) == 1 and "invalid Activity Date" in messages[0]
    activities, messages = parse_one(
        tmp_path, row("Buy", "($10.00)", symbol="AAPL", qty="x1", price="$10")
    )
    assert activities == []
    assert len(messages) == 1 and "invalid Quantity" in messages[0]


# --- formats and mappings (small CSVs) -----------------------------------------------


def test_utf8_bom_and_crlf(tmp_path: Path) -> None:
    path = tmp_path / "bom.csv"
    body = "\r\n".join([HEADER, row("INT", "$1.50", desc="Interest Payment"), ""])
    path.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    assert RobinhoodParser().detect(path)
    activities, messages = parse_with_warnings(path)
    assert messages == []
    assert activities == [act("3/1/2024", T.INTEREST, "Interest Payment", amount=D("1.50"))]


def test_multiline_description_with_crlf(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path,
        row(
            "Buy",
            "($100.00)",
            symbol="AAPL",
            desc="Apple\r\nCUSIP: 037833100",
            qty="1",
            price="$100.00",
        ),
        newline="\r\n",
    )
    (activity,) = RobinhoodParser().parse(path)
    assert activity.comment == "Apple"
    assert activity.amount == D("100.00")


@pytest.mark.parametrize(
    ("code", "amount", "expected"),
    [
        ("ACH", "$100.00", T.DEPOSIT),
        ("ACH", "($100.00)", T.WITHDRAWAL),
        ("RTP", "$100.00", T.DEPOSIT),
        ("RTP", "($100.00)", T.WITHDRAWAL),
        ("MINT", "$1.00", T.INTEREST),
        ("MINT", "($1.00)", T.FEE),
    ],
)
def test_sign_dependent_codes(tmp_path: Path, code: str, amount: str, expected: T) -> None:
    activities, messages = parse_one(tmp_path, row(code, amount))
    assert messages == []
    assert [(a.activity_type, a.amount) for a in activities] == [(expected, D(amount.strip("$()")))]


@pytest.mark.parametrize(
    ("code", "kind"),
    [("MDIV", T.DIVIDEND), ("GDBP", T.DEPOSIT), ("MTCH", T.DEPOSIT), ("SLIP", T.INTEREST)],
)
def test_income_codes(tmp_path: Path, code: str, kind: T) -> None:
    activities, _ = parse_one(tmp_path, row(code, "$2.00", symbol="AAPL"))
    assert [a.activity_type for a in activities] == [kind]


@pytest.mark.parametrize(
    ("code", "amount", "text"),
    [
        ("CDIV", "($1.00)", "reversal"),
        ("DTAX", "$1.00", "refund"),
        ("GOLD", "$5.00", "refund"),
    ],
)
def test_reversals_and_refunds_are_skipped_with_warning(
    tmp_path: Path, code: str, amount: str, text: str
) -> None:
    activities, messages = parse_one(tmp_path, row(code, amount, symbol="AAPL"))
    assert activities == []
    assert len(messages) == 1 and text in messages[0] and code in messages[0]


def test_unknown_code_skipped_with_warning(tmp_path: Path) -> None:
    activities, messages = parse_one(tmp_path, row("ZZZ", "$1.00"))
    assert activities == []
    assert len(messages) == 1 and "unsupported trans code 'ZZZ'" in messages[0]


def test_quantity_suffix_ignored(tmp_path: Path) -> None:
    activities, _ = parse_one(
        tmp_path, row("Buy", "($50.00)", symbol="AAPL", qty="5S", price="$10.00")
    )
    assert activities[0].quantity == D(5)


def test_buy_without_amount_leaves_amount_none(tmp_path: Path) -> None:
    activities, _ = parse_one(tmp_path, row("Buy", "", symbol="AAPL", qty="2", price="$10.00"))
    assert activities[0].amount is None and activities[0].fee == 0


def test_sell_fee_not_derived_when_gap_too_large(tmp_path: Path) -> None:
    # gross 1000.00 vs amount 900.00: 10% gap, treated as averaged fills, not a fee.
    (activity,) = parse_one(
        tmp_path, row("Sell", "$900.00", symbol="AAPL", qty="10", price="$100.00")
    )[0]
    assert activity.fee == 0 and activity.amount == D("900.00")


@pytest.mark.parametrize(
    ("description", "ratio"),
    [
        ("Forward Split 2 for 1", D(2)),
        ("NVIDIA 10-for-1 stock split", D(10)),
        ("Reverse split 1:10", D("0.1")),
        ("3 for 2 split", D("1.5")),
    ],
)
def test_split_with_parsable_ratio(tmp_path: Path, description: str, ratio: Decimal) -> None:
    activities, messages = parse_one(
        tmp_path, row("SPL", symbol="NVDA", desc=description, qty="45")
    )
    assert messages == []
    assert activities == [act("3/1/2024", T.SPLIT, description, symbol="NVDA", amount=ratio)]


def test_split_without_symbol_is_skipped(tmp_path: Path) -> None:
    activities, messages = parse_one(tmp_path, row("SPR", desc="1 for 10"))
    assert activities == [] and len(messages) == 1
