from __future__ import annotations

import csv
import re
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from statement2csv.cli import app

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_FILES = {
    "fidelity": FIXTURES / "fidelity_statement.pdf",
    "schwab": FIXTURES / "schwab_statement.pdf",
    "robinhood": FIXTURES / "robinhood_activity.csv",
}

# Headers exactly as documented in docs/formats.md.
WEALTHFOLIO_HEADER = [
    "date", "symbol", "quantity", "activityType", "unitPrice", "currency", "fee", "amount",
    "comment",
]  # fmt: skip
GHOSTFOLIO_HEADER = [
    "Date", "Code", "DataSource", "Currency", "Price", "Quantity", "Action", "Fee", "Note",
]  # fmt: skip
HEADERS = {"wealthfolio": WEALTHFOLIO_HEADER, "ghostfolio": GHOSTFOLIO_HEADER}

WEALTHFOLIO_TYPES = {
    "BUY", "SELL", "SPLIT", "DIVIDEND", "INTEREST", "DEPOSIT", "WITHDRAWAL", "TRANSFER_IN",
    "TRANSFER_OUT", "FEE", "TAX", "CREDIT", "ADJUSTMENT",
}  # fmt: skip
GHOSTFOLIO_ACTIONS = {"buy", "sell", "dividend", "fee", "interest"}

# Activity counts per fixture (see the parser tests) and how many of them Ghostfolio can't
# represent (DEPOSIT / WITHDRAWAL / SPLIT).
TOTALS = {"fidelity": 19, "schwab": 18, "robinhood": 17}
CASH_MOVEMENTS = {"fidelity": 4, "schwab": 3, "robinhood": 3}

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PLAIN_NUMBER = re.compile(r"^\d+(\.\d+)?$")


def convert(fixture: str, fmt: str, out: Path, *extra: str):
    args = ["convert", str(FIXTURE_FILES[fixture]), "-f", fmt, "-o", str(out), *extra]
    return runner.invoke(app, args)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def find(rows: list[dict[str, str]], **match: str) -> dict[str, str]:
    hits = [r for r in rows if all(r[k] == v for k, v in match.items())]
    assert len(hits) == 1, f"expected exactly one row matching {match}, got {hits}"
    return hits[0]


@pytest.fixture(params=sorted(FIXTURE_FILES))
def fixture(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture(params=["wealthfolio", "ghostfolio"])
def fmt(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def exported(fixture: str, fmt: str, tmp_path: Path) -> list[dict[str, str]]:
    out = tmp_path / "out.csv"
    result = convert(fixture, fmt, out, "--broker", "auto")
    assert result.exit_code == 0, result.output
    return read_rows(out)


def test_header_matches_docs(fixture: str, fmt: str, tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    assert convert(fixture, fmt, out, "--broker", "auto").exit_code == 0
    assert out.read_text(encoding="utf-8").splitlines()[0] == ",".join(HEADERS[fmt])


def test_row_count_follows_parsed_activities(exported, fixture: str, fmt: str) -> None:
    expected = TOTALS[fixture] - (CASH_MOVEMENTS[fixture] if fmt == "ghostfolio" else 0)
    assert len(exported) == expected


def test_dates_are_iso_and_sorted(exported, fmt: str) -> None:
    column = "date" if fmt == "wealthfolio" else "Date"
    dates = [r[column] for r in exported]
    assert all(ISO_DATE.match(d) for d in dates)
    assert dates == sorted(dates)


def test_wealthfolio_activity_types_and_currency(fixture: str, tmp_path: Path) -> None:
    out = tmp_path / "w.csv"
    assert convert(fixture, "wealthfolio", out).exit_code == 0
    rows = read_rows(out)
    assert {r["activityType"] for r in rows} <= WEALTHFOLIO_TYPES
    assert {r["currency"] for r in rows} == {"USD"}
    for r in rows:
        if r["activityType"] in ("DEPOSIT", "WITHDRAWAL", "DIVIDEND", "INTEREST", "TAX"):
            assert Decimal(r["amount"]) > 0


def test_ghostfolio_actions_and_numeric_cells(fixture: str, tmp_path: Path) -> None:
    out = tmp_path / "g.csv"
    assert convert(fixture, "ghostfolio", out).exit_code == 0
    rows = read_rows(out)
    assert {r["Action"] for r in rows} <= GHOSTFOLIO_ACTIONS
    for r in rows:
        for column in ("Price", "Quantity", "Fee"):
            assert PLAIN_NUMBER.match(r[column]), f"{column}={r[column]!r} in {r}"
        assert r["Currency"] == "USD"


def test_ghostfolio_skips_cash_movements_with_messages(fixture: str, tmp_path: Path) -> None:
    result = convert(fixture, "ghostfolio", tmp_path / "g.csv")
    skipped = [line for line in result.output.splitlines() if line.startswith("Skipped ")]
    assert len(skipped) == CASH_MOVEMENTS[fixture]
    assert all("Ghostfolio has no" in line for line in skipped)
    assert f"skipped {CASH_MOVEMENTS[fixture]}" in result.output


# --- spot checks ---------------------------------------------------------------------

SPOT_WEALTHFOLIO = {
    "fidelity": [
        # buy with fee, parenthesis-free negative amount in the PDF
        {"date": "2024-02-02", "symbol": "AAPL", "activityType": "BUY", "quantity": "10.5",
         "unitPrice": "185.2", "fee": "4.95", "amount": "1949.55"},
        {"date": "2024-02-15", "symbol": "VTI", "activityType": "DIVIDEND", "amount": "45.67"},
        {"date": "2024-02-16", "symbol": "NVS", "activityType": "TAX", "amount": "13.23"},
        {"date": "2024-02-01", "symbol": "", "activityType": "DEPOSIT", "amount": "25000"},
    ],
    "schwab": [
        {"date": "2024-01-03", "symbol": "AAPL", "activityType": "BUY", "quantity": "10.5",
         "unitPrice": "185.2", "fee": "4.95", "amount": "1949.55"},
        {"date": "2024-01-16", "symbol": "VTI", "activityType": "DIVIDEND", "amount": "45.67"},
        {"date": "2024-01-17", "symbol": "NVS", "activityType": "TAX", "amount": "13.23"},
        {"date": "2024-01-25", "symbol": "", "activityType": "FEE", "amount": "15"},
    ],
    "robinhood": [
        {"date": "2024-01-10", "symbol": "AAPL", "activityType": "BUY", "quantity": "40",
         "unitPrice": "185.5", "fee": "0", "amount": "7420"},
        {"date": "2024-03-22", "symbol": "MSFT", "activityType": "SELL", "quantity": "20",
         "unitPrice": "425.2", "fee": "0.21", "amount": "8503.79"},
        {"date": "2024-02-15", "symbol": "AAPL", "activityType": "DIVIDEND", "amount": "9.6"},
        {"date": "2024-03-15", "symbol": "", "activityType": "WITHDRAWAL", "amount": "2500"},
    ],
}  # fmt: skip

SPOT_GHOSTFOLIO = {
    "fidelity": [
        {"Date": "2024-02-02", "Code": "AAPL", "Action": "buy", "Quantity": "10.5",
         "Price": "185.2", "Fee": "4.95"},
        # dividend: total as Price x Quantity 1
        {"Date": "2024-02-15", "Code": "VTI", "Action": "dividend", "Quantity": "1",
         "Price": "45.67", "Fee": "0"},
        {"Date": "2024-02-29", "Code": "912797ZZ1", "Action": "interest", "Price": "125"},
    ],
    "schwab": [
        {"Date": "2024-01-03", "Code": "AAPL", "Action": "buy", "Quantity": "10.5",
         "Price": "185.2", "Fee": "4.95"},
        {"Date": "2024-01-16", "Code": "VTI", "Action": "dividend", "Quantity": "1",
         "Price": "45.67"},
        {"Date": "2024-01-31", "Code": "Interest", "Action": "interest", "Price": "5.43"},
    ],
    "robinhood": [
        {"Date": "2024-01-10", "Code": "AAPL", "Action": "buy", "Quantity": "40",
         "Price": "185.5", "Fee": "0"},
        {"Date": "2024-03-22", "Code": "MSFT", "Action": "sell", "Quantity": "20",
         "Price": "425.2", "Fee": "0.21"},
        {"Date": "2024-03-28", "Code": "Fee", "Action": "fee", "Price": "0", "Quantity": "0",
         "Fee": "5"},
    ],
}  # fmt: skip

SPOT_TAX = {  # Ghostfolio row for the tax activity: fee action, Note starts with "Tax"
    "fidelity": {"Date": "2024-02-16", "Code": "NVS", "Fee": "13.23"},
    "schwab": {"Date": "2024-01-17", "Code": "NVS", "Fee": "13.23"},
    "robinhood": {"Date": "2024-04-11", "Code": "TSM", "Fee": "1.39"},
}


def test_wealthfolio_spot_rows(fixture: str, tmp_path: Path) -> None:
    out = tmp_path / "w.csv"
    assert convert(fixture, "wealthfolio", out).exit_code == 0
    rows = read_rows(out)
    for expected in SPOT_WEALTHFOLIO[fixture]:
        row = find(rows, date=expected["date"], symbol=expected["symbol"],
                   activityType=expected["activityType"])  # fmt: skip
        for column, value in expected.items():
            assert row[column] == value, (column, row)


def test_ghostfolio_spot_rows(fixture: str, tmp_path: Path) -> None:
    out = tmp_path / "g.csv"
    assert convert(fixture, "ghostfolio", out).exit_code == 0
    rows = read_rows(out)
    for expected in SPOT_GHOSTFOLIO[fixture]:
        row = find(rows, Date=expected["Date"], Code=expected["Code"], Action=expected["Action"])
        for column, value in expected.items():
            assert row[column] == value, (column, row)


def test_ghostfolio_tax_exported_as_fee_with_tax_note(fixture: str, tmp_path: Path) -> None:
    out = tmp_path / "g.csv"
    assert convert(fixture, "ghostfolio", out).exit_code == 0
    spec = SPOT_TAX[fixture]
    row = find(read_rows(out), Date=spec["Date"], Code=spec["Code"], Action="fee", Fee=spec["Fee"])
    assert row["Note"].startswith("Tax")
    assert row["Price"] == "0" and row["Quantity"] == "0"
    assert row["DataSource"] == "MANUAL"


# --- options and warnings ------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["wealthfolio", "ghostfolio"])
def test_explicit_broker_matches_auto(fixture: str, fmt: str, tmp_path: Path) -> None:
    auto, explicit = tmp_path / "auto.csv", tmp_path / "explicit.csv"
    assert convert(fixture, fmt, auto, "--broker", "auto").exit_code == 0
    result = convert(fixture, fmt, explicit, "--broker", fixture)
    assert result.exit_code == 0, result.output
    assert explicit.read_bytes() == auto.read_bytes()


def test_explicit_wrong_broker_is_an_error(tmp_path: Path) -> None:
    result = convert("schwab", "wealthfolio", tmp_path / "x.csv", "--broker", "fidelity")
    assert result.exit_code == 1
    assert "Error:" in result.output and "not a Fidelity" in result.output
    assert not (tmp_path / "x.csv").exists()


def test_summary_line_reports_count(fixture: str, tmp_path: Path) -> None:
    result = convert(fixture, "wealthfolio", tmp_path / "w.csv")
    assert f"wrote {TOTALS[fixture]} activities" in result.output


@pytest.mark.parametrize(
    ("fixture", "texts"),
    [
        ("fidelity", ["Transfer of Assets", "unsupported transaction"]),
        ("schwab", ["Journaled Shares"]),
        ("robinhood", ["NVDA", "split ratio", "BTO"]),
    ],
)
def test_parser_warnings_are_surfaced(fixture: str, texts: list[str], tmp_path: Path) -> None:
    result = convert(fixture, "wealthfolio", tmp_path / "w.csv")
    assert result.exit_code == 0
    warning_lines = [ln for ln in result.output.splitlines() if ln.startswith("Warning: ")]
    expected_count = {"fidelity": 1, "schwab": 1, "robinhood": 2}[fixture]
    assert len(warning_lines) == expected_count
    joined = "\n".join(warning_lines)
    for text in texts:
        assert text in joined


def test_stdout_output(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["convert", str(FIXTURE_FILES["robinhood"]), "-f", "ghostfolio", "-o", "-"]
    )
    assert result.exit_code == 0
    assert ",".join(GHOSTFOLIO_HEADER) in result.output


def test_unwritable_output_is_a_clean_error(tmp_path: Path) -> None:
    result = convert("schwab", "wealthfolio", tmp_path / "missing-dir" / "out.csv")
    assert result.exit_code == 1
    assert "Error: cannot write" in result.output
    assert "Traceback" not in result.output


def test_no_activities_is_an_error_and_writes_nothing(tmp_path: Path) -> None:
    empty = tmp_path / "empty.csv"
    empty.write_text(
        '"Activity Date","Process Date","Settle Date","Instrument","Description",'
        '"Trans Code","Quantity","Price","Amount"\n',
        encoding="utf-8",
    )
    out = tmp_path / "out.csv"
    result = runner.invoke(app, ["convert", str(empty), "-o", str(out)])
    assert result.exit_code == 1
    assert "no activities found" in result.output
    assert not out.exists()


# --- spreadsheet and gains ----------------------------------------------------------

SPREADSHEET_HEADER = [
    "date", "broker", "account", "type", "symbol", "description", "quantity", "price",
    "amount", "fees", "currency",
]  # fmt: skip
BROKER_NAMES = {"fidelity": "Fidelity", "schwab": "Charles Schwab", "robinhood": "Robinhood"}


@pytest.mark.parametrize("fmt_name", ["spreadsheet", "csv"])
def test_spreadsheet_keeps_every_activity(fixture: str, fmt_name: str, tmp_path: Path) -> None:
    out = tmp_path / "s.csv"
    result = convert(fixture, fmt_name, out)
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8").splitlines()[0] == ",".join(SPREADSHEET_HEADER)
    rows = read_rows(out)
    assert len(rows) == TOTALS[fixture]
    assert {r["broker"] for r in rows} == {BROKER_NAMES[fixture]}
    assert [r["date"] for r in rows] == sorted(r["date"] for r in rows)
    for r in rows:
        amount = Decimal(r["amount"]) if r["amount"] else None
        if r["type"] in ("Buy", "Withdrawal", "Fee", "Tax"):
            assert amount is not None and amount < 0, r
        elif r["type"] in ("Sell", "Deposit", "Dividend", "Interest"):
            assert amount is not None and amount > 0, r
        if r["type"] == "Sell":
            assert Decimal(r["quantity"]) < 0
        if r["type"] not in ("Buy", "Sell"):
            assert r["quantity"] == "" and r["price"] == ""


def test_spreadsheet_spot_row(tmp_path: Path) -> None:
    out = tmp_path / "s.csv"
    assert convert("robinhood", "spreadsheet", out).exit_code == 0
    row = find(read_rows(out), date="2024-03-22", symbol="MSFT")
    assert (row["type"], row["quantity"], row["price"], row["amount"], row["fees"]) == (
        "Sell", "-20", "425.2", "8503.79", "0.21",
    )  # fmt: skip


GAINS = {
    "robinhood": [
        {"description": "30 sh. AAPL", "date_acquired": "2024-01-10", "date_sold": "2024-02-20",
         "proceeds": "5469.18", "cost_basis": "5565.00", "gain_loss": "-95.82", "term": "short"},
        {"description": "20 sh. MSFT", "date_acquired": "2024-01-12", "date_sold": "2024-03-22",
         "proceeds": "8503.79", "cost_basis": "7769.40", "gain_loss": "734.39", "term": "short"},
    ],
    "fidelity": [
        # MSFT was bought before this statement: no basis, flagged.
        {"description": "8.25 sh. MSFT", "date_acquired": "", "date_sold": "2024-02-09",
         "proceeds": "3096.98", "cost_basis": "", "gain_loss": "", "term": "unknown"},
        # 4 of the 10.5 shares bought for 1949.55 (fee included): 742.685... -> 742.69
        {"description": "4 sh. AAPL", "date_acquired": "2024-02-02", "date_sold": "2024-02-20",
         "proceeds": "760.38", "cost_basis": "742.69", "gain_loss": "17.69", "term": "short"},
    ],
}  # fmt: skip


@pytest.mark.parametrize("fixture_name", sorted(GAINS))
def test_gains_report(fixture_name: str, tmp_path: Path) -> None:
    out = tmp_path / "g.csv"
    result = convert(fixture_name, "gains", out)
    assert result.exit_code == 0, result.output
    assert read_rows(out) == GAINS[fixture_name]
    assert "Realized gains (FIFO):" in result.output
    assert "Not tax advice" in result.output
    no_basis = "8.25 shares have no cost basis" in result.output
    assert no_basis == (fixture_name == "fidelity")


def test_gains_xlsx(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    out = tmp_path / "g.xlsx"
    result = convert("robinhood", "gains", out, "--xlsx")
    assert result.exit_code == 0, result.output
    wb = openpyxl.load_workbook(out)
    assert wb.worksheets[0].max_row == 3
    assert "Summary" in wb.sheetnames
