from __future__ import annotations

import csv
import datetime as dt
import io
from decimal import Decimal
from pathlib import Path

import pytest

from statement2csv.exporters import GainsExporter, get_exporter
from statement2csv.exporters.gains import DISCLAIMER, holding_term, match_fifo, one_year_after
from statement2csv.models import Activity, ActivityType

D = Decimal
HEADER = [
    "description", "date_acquired", "date_sold", "proceeds", "cost_basis", "gain_loss", "term",
]  # fmt: skip


def buy(day: str, qty, price, fee=0, symbol="AAPL", **kwargs) -> Activity:
    return Activity(
        date=dt.date.fromisoformat(day),
        activity_type=ActivityType.BUY,
        symbol=symbol,
        quantity=D(str(qty)),
        unit_price=D(str(price)),
        fee=D(str(fee)),
        currency=kwargs.pop("currency", "USD"),
        **kwargs,
    )


def sell(day: str, qty, price, fee=0, symbol="AAPL", **kwargs) -> Activity:
    return Activity(
        date=dt.date.fromisoformat(day),
        activity_type=ActivityType.SELL,
        symbol=symbol,
        quantity=D(str(qty)),
        unit_price=D(str(price)),
        fee=D(str(fee)),
        currency=kwargs.pop("currency", "USD"),
        **kwargs,
    )


def report(activities):
    buf = io.StringIO()
    result = GainsExporter().export(activities, buf)
    buf.seek(0)
    reader = csv.DictReader(buf)
    rows = list(reader)
    return reader.fieldnames, rows, result


def cols(rows, *names):
    return [tuple(r[n] for n in names) for r in rows]


def test_full_lot_with_fees_in_basis_and_proceeds() -> None:
    header, rows, result = report(
        [buy("2024-01-02", 10, 100, fee=5), sell("2024-03-01", 10, 120, fee=3)]
    )
    assert header == HEADER
    assert rows == [
        {
            "description": "10 sh. AAPL",
            "date_acquired": "2024-01-02",
            "date_sold": "2024-03-01",
            "proceeds": "1197.00",  # 1200 - 3
            "cost_basis": "1005.00",  # 1000 + 5
            "gain_loss": "192.00",
            "term": "short",
        }
    ]
    assert result.written == 1
    assert not result.warnings and not result.skipped


def test_partial_lot_then_rest_of_lot() -> None:
    _, rows, _ = report(
        [
            buy("2024-01-02", 10, 100, fee=10),  # basis 1010, 101/share
            sell("2024-02-01", 3, 110),
            sell("2024-03-01", 7, 90),
        ]
    )
    assert cols(rows, "description", "proceeds", "cost_basis", "gain_loss") == [
        ("3 sh. AAPL", "330.00", "303.00", "27.00"),
        ("7 sh. AAPL", "630.00", "707.00", "-77.00"),  # a loss
    ]


def test_sell_spanning_lots_is_split_fifo_and_pieces_add_up() -> None:
    _, rows, _ = report(
        [
            buy("2024-01-02", 5, 100),
            buy("2024-01-10", 5, 110),
            buy("2024-01-20", 5, 120),
            sell("2024-02-01", 12, 130, fee=12),  # net 1548, 129/share
        ]
    )
    assert cols(rows, "description", "date_acquired", "proceeds", "cost_basis") == [
        ("5 sh. AAPL", "2024-01-02", "645.00", "500.00"),
        ("5 sh. AAPL", "2024-01-10", "645.00", "550.00"),
        ("2 sh. AAPL", "2024-01-20", "258.00", "240.00"),
    ]
    assert sum(D(r["proceeds"]) for r in rows) == D(1548)
    # The rest of the third lot is used next.
    _, rows, _ = report(
        [
            buy("2024-01-02", 5, 100),
            buy("2024-01-20", 5, 120),
            sell("2024-02-01", 7, 130),
            sell("2024-02-02", 3, 130),
        ]
    )
    assert cols(rows, "date_acquired", "description", "cost_basis") == [
        ("2024-01-02", "5 sh. AAPL", "500.00"),
        ("2024-01-20", "2 sh. AAPL", "240.00"),
        ("2024-01-20", "3 sh. AAPL", "360.00"),
    ]


def test_uneven_split_proceeds_still_sum_to_total() -> None:
    # 1/3 shares: per-piece rounding must not lose or invent a cent overall.
    activities = [buy("2024-01-0" + str(i), 1, 10) for i in (1, 2, 3)]
    activities.append(sell("2024-02-01", 3, D("33.33"), fee=D("0.01")))  # net 99.98
    _, rows, _ = report(activities)
    assert len(rows) == 3
    assert sum(D(r["proceeds"]) for r in rows) == D("99.98")
    disposals, _ = match_fifo(activities)
    assert sum(d.proceeds for d in disposals) == D("99.98")  # exact before rounding


def test_partial_lot_basis_is_exact_over_many_sells() -> None:
    activities = [buy("2024-01-02", 3, 10, fee=1)]  # basis 31
    activities += [sell(f"2024-02-0{i}", 1, 12) for i in (1, 2, 3)]
    disposals, _ = match_fifo(activities)
    assert sum(d.basis for d in disposals) == D(31)


def test_broker_totals_used_for_basis_and_proceeds() -> None:
    _, rows, _ = report(
        [
            buy("2024-01-02", 10, 100, fee=5, amount=D("1006.10")),
            sell("2024-03-01", 10, 120, fee=3, amount=D("1196.50")),
        ]
    )
    assert cols(rows, "proceeds", "cost_basis", "gain_loss") == [("1196.50", "1006.10", "190.40")]


@pytest.mark.parametrize(
    ("acquired", "sold", "term"),
    [
        ("2023-01-15", "2024-01-15", "short"),  # exactly one year: not *more* than one year
        ("2023-01-15", "2024-01-16", "long"),
        ("2023-01-15", "2023-06-01", "short"),
        ("2024-02-29", "2025-02-28", "short"),  # leap day purchase
        ("2024-02-29", "2025-03-01", "long"),
        ("2023-03-01", "2024-02-29", "short"),
        ("2023-03-01", "2024-03-02", "long"),
    ],
)
def test_holding_term(acquired: str, sold: str, term: str) -> None:
    assert holding_term(dt.date.fromisoformat(acquired), dt.date.fromisoformat(sold)) == term


def test_one_year_after_leap_day() -> None:
    assert one_year_after(dt.date(2024, 2, 29)) == dt.date(2025, 2, 28)
    assert one_year_after(dt.date(2023, 7, 4)) == dt.date(2024, 7, 4)


def test_one_sale_across_short_and_long_lots() -> None:
    _, rows, result = report(
        [
            buy("2022-06-01", 5, 50),
            buy("2023-09-01", 5, 80),
            sell("2024-03-01", 10, 100),
        ]
    )
    assert cols(rows, "date_acquired", "gain_loss", "term") == [
        ("2022-06-01", "250.00", "long"),
        ("2023-09-01", "100.00", "short"),
    ]
    summary = "\n".join(result.summary)
    assert "Short-term:" in summary and "Long-term:" in summary
    assert "gain/loss         100.00 USD" in summary
    assert "gain/loss         250.00 USD" in summary
    assert "Total:      gain/loss 350.00 USD" in summary
    assert result.summary[-1] == DISCLAIMER


def test_sell_without_enough_buys_warns_and_leaves_basis_blank() -> None:
    _, rows, result = report([buy("2024-01-02", 4, 100), sell("2024-02-01", 10, 110)])
    assert cols(rows, *HEADER[:2], *HEADER[3:]) == [
        ("4 sh. AAPL", "2024-01-02", "440.00", "400.00", "40.00", "short"),
        ("6 sh. AAPL", "", "660.00", "", "", "unknown"),
    ]
    assert len(result.warnings) == 1
    assert "only 4 shares were bought earlier" in result.warnings[0]
    assert "6 shares have no cost basis" in result.warnings[0]
    summary = "\n".join(result.summary)
    assert "Total:      gain/loss 40.00 USD" in summary  # unknown basis not counted
    assert "Not included: 660.00 USD of proceeds with unknown cost basis" in summary


def test_sell_with_no_buys_at_all() -> None:
    _, rows, result = report([sell("2024-02-01", 2, 50)])
    assert cols(rows, "proceeds", "cost_basis", "term") == [("100.00", "", "unknown")]
    assert "no shares were bought earlier" in result.warnings[0]


def test_buys_after_the_sell_are_not_used() -> None:
    _, rows, result = report([sell("2024-02-01", 2, 50), buy("2024-02-05", 2, 40)])
    assert cols(rows, "term") == [("unknown",)]
    assert result.warnings


def test_same_day_buy_listed_after_sell_is_matched() -> None:
    # Statements often list newest first; a day trade must still match.
    _, rows, result = report([sell("2024-02-01", 2, 50), buy("2024-02-01", 2, 45)])
    assert cols(rows, "date_acquired", "gain_loss", "term") == [("2024-02-01", "10.00", "short")]
    assert not result.warnings


def test_same_day_buy_does_not_jump_ahead_of_older_lots() -> None:
    _, rows, _ = report(
        [buy("2024-01-02", 2, 10), sell("2024-02-01", 2, 50), buy("2024-02-01", 2, 45)]
    )
    assert cols(rows, "date_acquired") == [("2024-01-02",)]


def test_input_order_does_not_matter() -> None:
    activities = [buy("2024-01-02", 5, 100), buy("2023-01-02", 5, 80), sell("2024-06-01", 5, 120)]
    _, rows, _ = report(list(reversed(activities)))
    assert cols(rows, "date_acquired", "term") == [("2023-01-02", "long")]


def test_symbols_accounts_and_currencies_are_separate_pools() -> None:
    header, rows, result = report(
        [
            buy("2024-01-02", 5, 100, symbol="AAPL", account="Taxable"),
            buy("2024-01-03", 5, 50, symbol="MSFT", account="Taxable"),
            buy("2024-01-04", 5, 10, symbol="AAPL", account="IRA"),
            sell("2024-02-01", 5, 60, symbol="MSFT", account="Taxable"),
            sell("2024-02-01", 5, 20, symbol="AAPL", account="IRA"),
            sell("2024-02-02", 1, 1, symbol="AAPL", account="Taxable", currency="EUR"),
        ]
    )
    assert header == [*HEADER, "account"]
    assert cols(rows, "description", "cost_basis", "account") == [
        ("5 sh. MSFT", "250.00", "Taxable"),
        ("5 sh. AAPL", "50.00", "IRA"),
        ("1 sh. AAPL", "", "Taxable"),  # the USD lot can't cover a EUR sale
    ]
    assert "in account Taxable" in result.warnings[0]
    summary = "\n".join(result.summary)
    assert "EUR" in summary and "USD" in summary


def test_split_multiplies_open_lot_quantities_keeping_basis() -> None:
    _, rows, result = report(
        [
            buy("2024-01-02", 10, 500),  # basis 5000
            Activity(
                date=dt.date(2024, 6, 10),
                activity_type=ActivityType.SPLIT,
                symbol="AAPL",
                amount=D(10),
                currency="USD",
            ),
            sell("2024-07-01", 40, 60),
        ]
    )
    assert cols(rows, "description", "proceeds", "cost_basis", "gain_loss") == [
        ("40 sh. AAPL", "2400.00", "2000.00", "400.00")
    ]
    assert not result.warnings


def test_non_trade_activities_are_ignored_not_skipped() -> None:
    other = [
        Activity(date=dt.date(2024, 1, 1), activity_type="DEPOSIT", amount=D(1), currency="USD"),
        Activity(
            date=dt.date(2024, 1, 5),
            activity_type="DIVIDEND",
            symbol="AAPL",
            amount=D(1),
            currency="USD",
        ),
    ]
    _, rows, result = report([*other, buy("2024-01-02", 1, 1), sell("2024-01-03", 1, 2)])
    assert len(rows) == 1
    assert not result.skipped and not result.warnings


def test_no_sells_gives_header_only_and_a_warning() -> None:
    header, rows, result = report([buy("2024-01-02", 1, 1)])
    assert header == HEADER and rows == []
    assert result.written == 0
    assert "no SELL activities" in result.warnings[0]
    assert result.summary == [DISCLAIMER]


def test_zero_quantity_trade_is_ignored_with_warning() -> None:
    _, rows, result = report([buy("2024-01-02", 0, 1), sell("2024-01-03", 1, 2)])
    assert any("no quantity" in w for w in result.warnings)
    assert cols(rows, "term") == [("unknown",)]


def test_fractional_shares() -> None:
    _, rows, _ = report([buy("2024-01-02", "0.523164", "448.05"), sell("2024-03-01", "0.2", 500)])
    assert cols(rows, "description", "proceeds", "cost_basis") == [
        ("0.2 sh. AAPL", "100.00", "89.61")
    ]


def test_registered_and_xlsx(tmp_path: Path) -> None:
    assert isinstance(get_exporter("gains"), GainsExporter)
    openpyxl = pytest.importorskip("openpyxl")
    out = tmp_path / "gains.xlsx"
    GainsExporter().export_xlsx([buy("2023-01-02", 2, 10), sell("2024-03-01", 2, 15)], out)
    wb = openpyxl.load_workbook(out)
    ws = wb.worksheets[0]
    rows = [[c.value for c in r] for r in ws.iter_rows()]
    assert rows[0] == HEADER
    assert rows[1][3:] == [30, 20, 10, "long"]
    assert ws["D2"].number_format == "#,##0.00"
    summary = [r[0] for r in wb["Summary"].iter_rows(values_only=True)]
    assert summary[-1] == DISCLAIMER


def test_reverse_split_with_repeating_ratio_leaves_no_dust() -> None:
    # Robinhood stores a 1-for-3 reverse split as new/old = 0.333...; 3 shares become
    # 0.999... unless the lot quantity is rounded after the split.
    _, rows, result = report(
        [
            buy("2024-01-02", 3, 10),
            Activity(
                date=dt.date(2024, 3, 1),
                activity_type=ActivityType.SPLIT,
                symbol="AAPL",
                amount=D(1) / D(3),
                currency="USD",
            ),
            sell("2024-04-01", 1, 40),
        ]
    )
    assert cols(rows, "description", "proceeds", "cost_basis", "term") == [
        ("1 sh. AAPL", "40.00", "30.00", "short")
    ]
    assert not result.warnings
