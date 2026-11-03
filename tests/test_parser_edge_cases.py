"""Edge cases for the PDF parsers, on small statements rendered by the fixture generators.

Each test patches the generator's module-level transaction data and renders a fresh PDF,
so the layout is exactly the one the main fixtures use.
"""

from __future__ import annotations

import importlib.util
import warnings
from decimal import Decimal
from pathlib import Path
from types import ModuleType

from statement2csv.models import Activity, ActivityType
from statement2csv.parsers.fidelity import FidelityParser
from statement2csv.parsers.schwab import SchwabParser

FIXTURES = Path(__file__).parent / "fixtures"
D = Decimal
T = ActivityType


def _load_generator(name: str) -> ModuleType:
    """A fresh copy of tests/fixtures/generate_<name>.py (patching it can't leak)."""
    spec = importlib.util.spec_from_file_location(f"_gen_{name}", FIXTURES / f"generate_{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse(parser, path: Path) -> tuple[list[Activity], list[str]]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        activities = parser.parse(path)
    return activities, [str(w.message) for w in caught]


def schwab(tmp_path: Path, rows: list[tuple[str, ...]]) -> tuple[list[Activity], list[str]]:
    """Render a Schwab statement whose Transaction Details are ``rows``, then parse it."""
    gen = _load_generator("schwab")
    gen.TRANSACTIONS = list(rows)
    gen.PAGE_BREAK_AFTER = len(rows)
    gen.OUTPUT = tmp_path / "schwab.pdf"
    gen.main()
    return _parse(SchwabParser(), gen.OUTPUT)


def fidelity(tmp_path: Path, trades: list[tuple[str, ...]]) -> tuple[list[Activity], list[str]]:
    """Render the Fidelity statement with ``trades`` as Securities Bought & Sold."""
    gen = _load_generator("fidelity")
    gen.TRADES = list(trades)
    gen.TRADES_PAGE_BREAK_AFTER = len(trades)
    gen.OUTPUT = tmp_path / "fidelity.pdf"
    gen.main()
    activities, messages = _parse(FidelityParser(), gen.OUTPUT)
    trades_only = [a for a in activities if a.activity_type in (T.BUY, T.SELL)]
    # The Fidelity fixture's own reinvestment BUY (SCHD) isn't in TRADES.
    return [a for a in trades_only if a.symbol != "SCHD"], messages


def _schwab_row(date, category, action, symbol, desc, qty="", price="", fee="", amount=""):
    return (date, category, action, symbol, desc, qty, price, fee, amount, "")


# --- Schwab --------------------------------------------------------------------------


def test_schwab_wrapped_description_starting_with_total_does_not_end_table(tmp_path):
    activities, messages = schwab(
        tmp_path,
        [
            _schwab_row(
                "01/03", "Purchase", "Buy", "ITOT",
                "ISHARES CORE S&P 500 INDEX TOTAL STOCK MARKET ETF FUND",
                "10.0000", "100.0000", "", "(1,000.00)",
            ),
            _schwab_row("01/05", "Purchase", "Buy", "AAPL", "APPLE INC",
                        "1.0000", "185.0000", "", "(185.00)"),
            _schwab_row("01/16", "Dividend", "Cash Dividend", "VTI", "VANGUARD",
                        amount="45.67"),
        ],
    )  # fmt: skip
    assert [a.symbol for a in activities] == ["ITOT", "AAPL", "VTI"]
    assert messages == []


def test_schwab_reversals_are_skipped_not_booked_in_the_wrong_direction(tmp_path):
    activities, messages = schwab(
        tmp_path,
        [
            _schwab_row("01/03", "Withdrawal", "Funds Paid", "", "WIRE RETURNED",
                        amount="1,000.00"),
            _schwab_row("01/04", "Deposit", "Funds Received", "", "DEPOSIT REVERSAL",
                        amount="(500.00)"),
            _schwab_row("01/05", "Dividend", "Cash Dividend", "VTI", "VANGUARD",
                        amount="(10.00)"),
            _schwab_row("01/06", "Fee", "Wire Fee", "", "FEE REFUND", amount="15.00"),
            _schwab_row("01/08", "Deposit", "Funds Received", "", "WIRED FUNDS RECEIVED",
                        amount="100.00"),
        ],
    )  # fmt: skip
    assert [(a.activity_type, a.amount) for a in activities] == [(T.DEPOSIT, D(100))]
    assert len(messages) == 4
    assert all("unexpected sign" in m for m in messages)


def test_schwab_bank_transfer_withdrawal_is_kept_but_sweep_is_ignored(tmp_path):
    activities, messages = schwab(
        tmp_path,
        [
            _schwab_row("01/05", "Withdrawal", "Bank Transfer", "",
                        "TRANSFER TO SCHWAB BANK CHECKING", amount="(2,000.00)"),
            _schwab_row("01/31", "Bank Sweep", "Bank Transfer", "",
                        "TRANSFER TO SCHWAB BANK SWEEP", amount="(5.43)"),
        ],
    )  # fmt: skip
    assert [(a.activity_type, a.amount) for a in activities] == [(T.WITHDRAWAL, D(2000))]
    assert messages == []


def test_schwab_negative_interest_becomes_fee(tmp_path):
    activities, _ = schwab(
        tmp_path, [_schwab_row("01/06", "Interest", "Margin Interest", "", "MARGIN INT",
                               amount="(12.50)")]
    )  # fmt: skip
    assert [(a.activity_type, a.amount) for a in activities] == [(T.FEE, D("12.50"))]


def test_schwab_options_skipped_and_bond_price_per_100_normalized(tmp_path):
    activities, messages = schwab(
        tmp_path,
        [
            _schwab_row("01/03", "Sale", "Sell to Open", "AAPL", "PUT APPLE INC $180",
                        "(1.0000)", "2.5000", "0.66", "249.34"),
            _schwab_row("01/05", "Purchase", "Buy", "912797ZZ1", "US TREASURY BILL",
                        "10,000.0000", "98.7650", "", "(9,876.50)"),
        ],
    )  # fmt: skip
    (bill,) = activities
    assert bill.unit_price == D("0.98765")
    assert bill.quantity * bill.unit_price == bill.amount
    assert len(messages) == 1 and "option" in messages[0]


def test_schwab_price_mismatch_warns_and_uses_cash_amount(tmp_path):
    activities, messages = schwab(
        tmp_path,
        [_schwab_row("01/05", "Purchase", "Buy", "XYZ", "XYZ CORP",
                     "10.0000", "12.0000", "", "(150.00)")],
    )  # fmt: skip
    (trade,) = activities
    assert trade.unit_price == D(15)
    assert len(messages) == 1 and "doesn't match the cash amount" in messages[0]


def test_schwab_invalid_date_is_a_warning_not_a_crash(tmp_path):
    activities, messages = schwab(
        tmp_path,
        [
            _schwab_row("02/30", "Dividend", "Cash Dividend", "VTI", "VANGUARD",
                        amount="45.67"),
            _schwab_row("", "", "Foreign Tax Paid", "VTI", "VANGUARD", amount="(6.85)"),
            _schwab_row("01/16", "Dividend", "Cash Dividend", "VNQ", "VANGUARD REIT",
                        amount="12.34"),
        ],
    )  # fmt: skip
    # The grouped tax row must not inherit an earlier date either.
    assert [a.symbol for a in activities] == ["VNQ"]
    assert len(messages) == 2 and "02/30" in messages[0]


def test_schwab_return_of_capital_is_not_a_dividend(tmp_path):
    activities, messages = schwab(
        tmp_path,
        [_schwab_row("01/16", "Dividend", "Return Of Capital", "VNQ", "VANGUARD REIT",
                     amount="5.00")],
    )  # fmt: skip
    assert activities == []
    assert len(messages) == 1 and "unsupported" in messages[0]


# --- Fidelity ------------------------------------------------------------------------


def test_fidelity_options_skipped_and_bond_price_per_100_normalized(tmp_path):
    activities, messages = fidelity(
        tmp_path,
        [
            ("02/02", "UNITED STATES TREAS BILLS ZERO CPN", "912797ZZ1", "You Bought",
             "10,000.000", "$98.7650", "-", "-9,876.50"),
            ("02/05", "PUT (AAPL) APPLE INC FEB 16 24 $180", "AAPL", "You Sold",
             "-1.000", "$2.5000", "$0.66", "249.34"),
            ("02/06", "APPLE INC", "AAPL", "You Bought",
             "1.000", "$185.0000", "-", "-185.00"),
        ],
    )  # fmt: skip
    bill, apple = activities
    assert (bill.symbol, bill.unit_price, bill.amount) == ("912797ZZ1", D("0.98765"), D("9876.50"))
    assert (apple.activity_type, apple.unit_price) == (T.BUY, D(185))
    option_warnings = [m for m in messages if "option" in m]
    assert len(option_warnings) == 1 and "PUT (AAPL)" in option_warnings[0]
