from __future__ import annotations

import datetime as dt
import io
from decimal import Decimal
from pathlib import Path

import pytest

from statement2csv.exporters import SpreadsheetExporter, get_exporter
from statement2csv.models import Activity

D = Decimal
HEADER = "date,broker,account,type,symbol,description,quantity,price,amount,fees,currency"


def act(day: int, activity_type: str, **kwargs) -> Activity:
    return Activity(
        date=dt.date(2024, 1, day), activity_type=activity_type, currency="USD", **kwargs
    )


def export(activities, broker: str | None = "Test Broker") -> list[str]:
    buf = io.StringIO()
    SpreadsheetExporter(broker=broker).export(activities, buf)
    return buf.getvalue().splitlines()


def test_header_and_signed_rows_for_every_type() -> None:
    lines = export(
        [
            act(1, "DEPOSIT", amount=D(5000), comment="ACH in"),
            act(2, "BUY", symbol="AAPL", quantity=D(10), unit_price=D("185.50"), fee=D("4.95")),
            act(3, "SELL", symbol="AAPL", quantity=D(4), unit_price=D(190), fee=D("0.05")),
            act(4, "DIVIDEND", symbol="AAPL", amount=D("2.40")),
            act(5, "INTEREST", amount=D("1.23")),
            act(6, "FEE", amount=D(25), comment="Account fee"),
            act(7, "TAX", symbol="AAPL", amount=D("0.36")),
            act(8, "WITHDRAWAL", amount=D(100)),
            act(9, "SPLIT", symbol="NVDA", amount=D(10)),
        ]
    )
    assert lines == [
        HEADER,
        "2024-01-01,Test Broker,,Deposit,,ACH in,,,5000,0,USD",
        # BUY without broker total: -(qty x price + fee)
        "2024-01-02,Test Broker,,Buy,AAPL,,10,185.5,-1859.95,4.95,USD",
        # SELL: negative quantity, net proceeds qty x price - fee
        "2024-01-03,Test Broker,,Sell,AAPL,,-4,190,759.95,0.05,USD",
        "2024-01-04,Test Broker,,Dividend,AAPL,,,,2.4,0,USD",
        "2024-01-05,Test Broker,,Interest,,,,,1.23,0,USD",
        # FEE: fees column carries the fee itself
        "2024-01-06,Test Broker,,Fee,,Account fee,,,-25,25,USD",
        "2024-01-07,Test Broker,,Tax,AAPL,,,,-0.36,0,USD",
        "2024-01-08,Test Broker,,Withdrawal,,,,,-100,0,USD",
        # SPLIT: the ratio is not cash; it goes into the description
        "2024-01-09,Test Broker,,Split,NVDA,10-for-1 split,,,,0,USD",
    ]


def test_broker_total_is_used_as_is() -> None:
    lines = export(
        [
            act(1, "BUY", symbol="X", quantity=D(1), unit_price=D(10), fee=D(1), amount=D("11.5")),
            act(2, "SELL", symbol="X", quantity=D(1), unit_price=D(12), fee=D(1), amount=D("10.9")),
        ]
    )
    assert [line.split(",")[8] for line in lines[1:]] == ["-11.5", "10.9"]


def test_per_share_dividend_goes_to_description_not_quantity() -> None:
    lines = export([act(1, "DIVIDEND", symbol="MSFT", quantity=D(5), unit_price=D("0.62"))])
    assert lines[1] == "2024-01-01,Test Broker,,Dividend,MSFT,5 shares x 0.62,,,3.1,0,USD"


def test_fee_only_fee_and_account_and_no_broker() -> None:
    lines = export([act(1, "FEE", fee=D("2.50"), account="Roth IRA")], broker=None)
    assert lines[1] == "2024-01-01,,Roth IRA,Fee,,,,,-2.5,2.5,USD"


def test_comment_with_comma_is_quoted() -> None:
    lines = export([act(1, "DEPOSIT", amount=D(1), comment="Wire, from bank")])
    assert '"Wire, from bank"' in lines[1]


def test_amount_column_sums_to_net_cash_flow() -> None:
    activities = [
        act(1, "DEPOSIT", amount=D(1000)),
        act(2, "BUY", symbol="A", quantity=D(2), unit_price=D(100), fee=D(1)),
        act(3, "DIVIDEND", symbol="A", amount=D(3)),
        act(4, "SELL", symbol="A", quantity=D(1), unit_price=D(120), fee=D(1)),
    ]
    amounts = [D(line.split(",")[8]) for line in export(activities)[1:]]
    assert sum(amounts) == D(1000) - D(201) + D(3) + D(119)


def test_csv_alias_and_case() -> None:
    assert isinstance(get_exporter("csv"), SpreadsheetExporter)
    assert isinstance(get_exporter(" Spreadsheet "), SpreadsheetExporter)
    with pytest.raises(ValueError, match="csv"):
        get_exporter("nope")


def test_xlsx_has_typed_cells(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    out = tmp_path / "out.xlsx"
    activities = [
        act(2, "BUY", symbol="AAPL", quantity=D(10), unit_price=D("185.50"), fee=D("4.95")),
        act(1, "DEPOSIT", amount=D(5000)),
    ]
    result = SpreadsheetExporter(broker="B").export_xlsx(activities, out)
    assert result.written == 2
    ws = openpyxl.load_workbook(out).active
    rows = [[c.value for c in r] for r in ws.iter_rows()]
    assert rows[0] == HEADER.split(",")
    assert rows[1][0].date() == dt.date(2024, 1, 1)  # sorted, a real date cell
    assert rows[1][1:4] == ["B", None, "Deposit"]
    assert rows[2][6:10] == [10, 185.5, -1859.95, 4.95]  # real numbers, not text
    assert ws.freeze_panes == "A2"


def test_xlsx_rejected_for_import_formats(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="CSV only"):
        get_exporter("wealthfolio").export_xlsx([], tmp_path / "x.xlsx")


def test_reverse_split_description() -> None:
    lines = export([act(1, "SPLIT", symbol="XYZ", amount=D(1) / D(3))])
    assert lines[1].split(",")[5] == "1-for-3 reverse split"
