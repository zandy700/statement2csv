"""Generate ``schwab_statement.pdf``: a SYNTHETIC Charles Schwab brokerage statement.

All names, addresses, account numbers and amounts are fake. The layout imitates the
current (single-table) Schwab One statement: page header with "Schwab One(R) Account of",
"Account Number" and "Statement Period", an Account Summary on page 1, positions on
page 2, and a "Transaction Details" table that continues onto page 3 under a
"Transaction Details (continued)" title with repeated two-line column headers.

Run:  .venv/bin/python tests/fixtures/generate_schwab.py
Output is deterministic (``invariant=1``): re-running gives a byte-identical PDF.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

OUTPUT = Path(__file__).with_name("schwab_statement.pdf")

# --------------------------------------------------------------------------------------
# Statement data (all synthetic). Test authors: derive expected activities from here.
# --------------------------------------------------------------------------------------

HOLDER = "JANE DOE"
ADDRESS = ["123 EXAMPLE STREET APT 4", "ANYTOWN CA 90000-0000"]
ACCOUNT_NUMBER = "1234-5678"
STATEMENT_PERIOD = "January 1-31, 2024"  # -> 2024-01-01 .. 2024-01-31

# Lines that must NOT become activities (summary values with $ and commas).
ACCOUNT_SUMMARY = [
    ("Beginning Account Value", "$123,456.78", "$118,002.10"),
    ("Deposits", "25,000.00", "25,000.00"),
    ("Withdrawals", "(3,500.00)", "(3,500.00)"),
    ("Dividends and Interest", "184.85", "184.85"),
    ("Market Appreciation/(Depreciation)", "1,234.56", "6,689.24"),
    ("Expenses", "(16.50)", "(16.50)"),
    ("Ending Account Value", "$146,359.69", "$146,359.69"),
]

POSITIONS = [
    # symbol, description, quantity, price, market value
    ("AAPL", "APPLE INC", "16.5000", "184.4000", "3,042.60"),
    ("VTI", "VANGUARD TOTAL STOCK MARKET ETF", "150.0000", "239.2000", "35,880.00"),
    ("FCNTX", "FIDELITY CONTRAFUND (FCNTX)", "520.1230", "16.4100", "8,535.22"),
    ("SCHD", "SCHWAB US DIVIDEND EQUITY ETF", "300.4000", "76.1000", "22,860.44"),
]

# Transaction Details rows, in printed order. Each row:
#   (date, category, action, symbol_or_cusip, description,
#    quantity, price, charges, amount, realized_gain)
# Cells are the exact printed strings ("" = blank cell). A blank date/category means the
# row belongs to the group above (as on real statements): it inherits the date above.
# Descriptions longer than the column width wrap onto a second line.
# PAGE_BREAK_AFTER rows are printed on page 2, the rest on page 3 (continued table).
# fmt: off
TRANSACTIONS = [
    # -> DEPOSIT 2024-01-02 amount 25000.00
    ("01/02", "Deposit", "Funds Received", "", "WIRED FUNDS RECEIVED",
     "", "", "", "25,000.00", ""),
    # -> BUY 2024-01-03 AAPL qty 10.5 price 185.20 fee 4.95 amount 1949.55
    ("01/03", "Purchase", "Buy", "AAPL", "APPLE INC",
     "10.5000", "185.2000", "4.95", "(1,949.55)", ""),
    # -> BUY 2024-01-05 VTI qty 50 price 236.12 fee 0 amount 11806.00
    ("01/05", "Purchase", "Buy", "VTI", "VANGUARD TOTAL STOCK MARKET ETF",
     "50.0000", "236.1200", "", "(11,806.00)", ""),
    # -> BUY 2024-01-08 99999X105 (CUSIP, no ticker) qty 125.125 price 16 fee 2.50
    #    amount 2004.50; leading-minus amount; description wraps onto a second line
    ("01/08", "Purchase", "Buy", "99999X105",
     "EXAMPLE GLOBAL INFRASTRUCTURE INCOME FUND INSTITUTIONAL CLASS",
     "125.1250", "16.0000", "2.50", "-2,004.50", ""),
    # -> SELL 2024-01-10 MSFT qty 8.25 price 375.40 fee 0.07 amount 3096.98
    ("01/10", "Sale", "Sell", "MSFT", "MICROSOFT CORP",
     "(8.2500)", "375.4000", "0.07", "3,096.98", "512.34"),
    # -> DIVIDEND 2024-01-16 VTI amount 45.67
    ("01/16", "Dividend", "Qualified Dividend", "VTI", "VANGUARD TOTAL STOCK MARKET ETF",
     "", "", "", "45.67", ""),
    # -> DIVIDEND 2024-01-16 VNQ amount 12.34
    ("01/16", "Dividend", "Non-Qualified Div", "VNQ", "VANGUARD REAL ESTATE ETF",
     "", "", "", "12.34", ""),
]
PAGE_BREAK_AFTER = len(TRANSACTIONS)
TRANSACTIONS += [
    # -> DIVIDEND 2024-01-17 NVS amount 88.20
    ("01/17", "Dividend", "Cash Dividend", "NVS", "NOVARTIS AG SPON ADR",
     "", "", "", "88.20", ""),
    # -> TAX 2024-01-17 NVS amount 13.23 (grouped row: blank date and category)
    ("", "", "Foreign Tax Paid", "NVS", "NOVARTIS AG SPON ADR",
     "", "", "", "(13.23)", ""),
    # -> FEE 2024-01-18 NVS amount 1.50
    ("01/18", "Expense", "ADR Mgmt Fee", "NVS", "NOVARTIS AG SPON ADR",
     "", "", "", "(1.50)", ""),
    # -> SELL 2024-01-19 AAPL qty 4 price 190.10 fee 0.02 amount 760.38
    ("01/19", "Sale", "Sell", "AAPL", "APPLE INC",
     "(4.0000)", "190.1000", "0.02", "760.38", "20.10"),
    # -> DIVIDEND 2024-01-22 SCHD amount 30.00
    ("01/22", "Dividend", "Qual Div Reinvest", "SCHD", "SCHWAB US DIVIDEND EQUITY ETF",
     "", "", "", "30.00", ""),
    # -> BUY 2024-01-22 SCHD qty 0.4 price 75 fee 0 amount 30.00 (reinvestment)
    ("01/22", "Purchase", "Reinvested Shares", "SCHD", "SCHWAB US DIVIDEND EQUITY ETF",
     "0.4000", "75.0000", "", "(30.00)", ""),
    # -> WITHDRAWAL 2024-01-24 amount 2500.00
    ("01/24", "Withdrawal", "MoneyLink Transfer", "", "TFR EXAMPLE BANK NA",
     "", "", "", "(2,500.00)", ""),
    # -> WITHDRAWAL 2024-01-25 amount 1000.00
    ("01/25", "Withdrawal", "Funds Paid", "", "WIRED FUNDS DISBURSED",
     "", "", "", "(1,000.00)", ""),
    # -> FEE 2024-01-25 amount 15.00 (blank date: inherits 01/25)
    ("", "Fee", "Wire Fee", "", "WIRE TRANSFER FEE",
     "", "", "", "(15.00)", ""),
    # -> skipped with a warning (unsupported action, no cash amount)
    ("01/29", "Other", "Journaled Shares", "VTI", "VANGUARD TOTAL STOCK MARKET ETF",
     "100.0000", "", "", "", ""),
    # -> INTEREST 2024-01-30 (no symbol) amount 3.21
    ("01/30", "Interest", "Credit Interest", "", "SCHWAB1 INT 12/28-01/29",
     "", "", "", "3.21", ""),
    # -> INTEREST 2024-01-31 (no symbol) amount 5.43
    ("01/31", "Interest", "Bank Interest", "", "BANK INT 010124-013124 SCHWAB BANK",
     "", "", "", "5.43", ""),
    # -> skipped silently (internal cash sweep, not a portfolio activity)
    ("01/31", "Bank Sweep", "Bank Transfer", "", "TRANSFER TO SCHWAB BANK SWEEP",
     "", "", "", "(5.43)", ""),
]
# fmt: on

# --------------------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------------------

PAGE_W, PAGE_H = letter
LEFT, RIGHT = 30, PAGE_W - 30
FONT, BOLD = "Helvetica", "Helvetica-Bold"
SIZE = 7
ROW_H = 9
TOTAL_PAGES = 3

# Text columns: left x. Numeric columns: right x (right-aligned).
COL_DATE, COL_CATEGORY, COL_ACTION, COL_SYMBOL, COL_DESC = 30, 56, 112, 184, 228
DESC_WIDTH = 114
NUM_RIGHT = {"quantity": 380, "price": 426, "charges": 470, "amount": 520, "realized": 582}


def header(c: canvas.Canvas, page: int) -> None:
    c.setFont(BOLD, 11)
    c.drawString(LEFT, PAGE_H - 40, "Schwab One® Account of")
    c.setFont(BOLD, 10)
    c.drawString(LEFT, PAGE_H - 54, HOLDER)
    c.setFont(FONT, 8)
    c.drawString(360, PAGE_H - 40, "Account Number")
    c.drawString(460, PAGE_H - 40, "Statement Period")
    c.setFont(BOLD, 9)
    c.drawString(360, PAGE_H - 52, ACCOUNT_NUMBER)
    c.drawString(460, PAGE_H - 52, STATEMENT_PERIOD)
    c.line(LEFT, PAGE_H - 62, RIGHT, PAGE_H - 62)


def footer(c: canvas.Canvas, page: int) -> None:
    c.setFont(FONT, 6)
    c.drawString(
        LEFT,
        30,
        'Brokerage products are offered by Charles Schwab & Co., Inc. ("Schwab"), '
        "Member SIPC. (0124-ZZZZ)",
    )
    c.setFont(FONT, 7)
    c.drawRightString(RIGHT, 30, f"Page {page} of {TOTAL_PAGES}")


def page1(c: canvas.Canvas) -> None:
    header(c, 1)
    c.setFont(BOLD, 14)
    c.drawString(LEFT, PAGE_H - 90, "charles SCHWAB")
    c.setFont(FONT, 9)
    y = PAGE_H - 120
    for line in [HOLDER, *ADDRESS]:
        c.drawString(LEFT, y, line)
        y -= 11
    y -= 20
    c.setFont(BOLD, 11)
    c.drawString(LEFT, y, "Account Summary")
    y -= 16
    c.setFont(BOLD, 8)
    c.drawRightString(400, y, "This Statement")
    c.drawRightString(500, y, "YTD")
    y -= 12
    c.setFont(FONT, 8)
    for label, this, ytd in ACCOUNT_SUMMARY:
        c.drawString(LEFT, y, label)
        c.drawRightString(400, y, this)
        c.drawRightString(500, y, ytd)
        y -= 11
    y -= 14
    c.drawString(LEFT, y, "Ending Account Value as of 01/31: $146,359.69")
    footer(c, 1)


def table_header(c: canvas.Canvas, y: float) -> float:
    """Two-line column headers, as on real statements. Returns y of the first row."""
    c.setFont(BOLD, SIZE)
    c.drawString(COL_SYMBOL, y, "Symbol/")
    c.drawRightString(NUM_RIGHT["price"], y, "Price/Rate")
    c.drawRightString(NUM_RIGHT["charges"], y, "Charges/")
    c.drawRightString(NUM_RIGHT["realized"], y, "Realized")
    y -= ROW_H
    c.drawString(COL_DATE, y, "Date")
    c.drawString(COL_CATEGORY, y, "Category")
    c.drawString(COL_ACTION, y, "Action")
    c.drawString(COL_SYMBOL, y, "CUSIP")
    c.drawString(COL_DESC, y, "Description")
    c.drawRightString(NUM_RIGHT["quantity"], y, "Quantity")
    c.drawRightString(NUM_RIGHT["price"], y, "per Share($)")
    c.drawRightString(NUM_RIGHT["charges"], y, "Interest($)")
    c.drawRightString(NUM_RIGHT["amount"], y, "Amount($)")
    c.drawRightString(NUM_RIGHT["realized"], y, "Gain/(Loss)($)")
    c.line(LEFT, y - 3, RIGHT, y - 3)
    return y - ROW_H - 2


def table_rows(c: canvas.Canvas, rows: list[tuple[str, ...]], y: float) -> float:
    c.setFont(FONT, SIZE)
    for date, cat, action, sym, desc, qty, price, charges, amount, realized in rows:
        c.drawString(COL_DATE, y, date)
        c.drawString(COL_CATEGORY, y, cat)
        c.drawString(COL_ACTION, y, action)
        c.drawString(COL_SYMBOL, y, sym)
        desc_lines = simpleSplit(desc, FONT, SIZE, DESC_WIDTH)
        for i, line in enumerate(desc_lines):
            c.drawString(COL_DESC, y - i * ROW_H, line)
        for key, value in zip(NUM_RIGHT, (qty, price, charges, amount, realized), strict=True):
            if value:
                c.drawRightString(NUM_RIGHT[key], y, value)
        y -= ROW_H * len(desc_lines) + 3
    return y


def total_amount() -> str:
    total = Decimal(0)
    for row in TRANSACTIONS:
        amount = row[8].replace(",", "")
        if not amount:
            continue
        if amount.startswith("("):
            total -= Decimal(amount.strip("()"))
        else:
            total += Decimal(amount)
    text = f"{abs(total):,.2f}"
    return f"({text})" if total < 0 else text


def page2(c: canvas.Canvas) -> None:
    header(c, 2)
    y = PAGE_H - 85
    c.setFont(BOLD, 10)
    c.drawString(LEFT, y, "Positions - Equities and Funds")
    y -= 14
    c.setFont(BOLD, SIZE)
    for x, label in ((LEFT, "Symbol"), (90, "Description")):
        c.drawString(x, y, label)
    for x, label in ((380, "Quantity"), (450, "Price($)"), (530, "Market Value($)")):
        c.drawRightString(x, y, label)
    y -= ROW_H + 2
    c.setFont(FONT, SIZE)
    for sym, desc, qty, price, value in POSITIONS:
        c.drawString(LEFT, y, sym)
        c.drawString(90, y, desc)
        c.drawRightString(380, y, qty)
        c.drawRightString(450, y, price)
        c.drawRightString(530, y, value)
        y -= ROW_H
    c.setFont(BOLD, SIZE)
    c.drawString(LEFT, y, "Total Positions")
    c.drawRightString(530, y, "$70,318.26")
    y -= 24

    c.setFont(BOLD, 10)
    c.drawString(LEFT, y, "Transactions - Summary")
    y -= 13
    c.setFont(FONT, SIZE)
    c.drawString(
        LEFT,
        y,
        "Beginning Cash* as of 01/01 $ 5,210.33 + Deposits $ 25,000.00 + Withdrawals "
        "$ (3,500.00) + Purchases $ (15,790.05) + Sales $ 3,857.36",
    )
    y -= ROW_H
    c.drawString(
        LEFT, y, "+ Dividends/Interest $ 184.85 + Expenses $ (16.50) = Ending Cash* as of 01/31"
    )
    y -= 24

    c.setFont(BOLD, 10)
    c.drawString(LEFT, y, "Transaction Details")
    y -= 14
    y = table_header(c, y)
    table_rows(c, TRANSACTIONS[:PAGE_BREAK_AFTER], y)
    footer(c, 2)


def page3(c: canvas.Canvas) -> None:
    header(c, 3)
    y = PAGE_H - 85
    c.setFont(BOLD, 10)
    c.drawString(LEFT, y, "Transaction Details (continued)")
    y -= 14
    y = table_header(c, y)
    y = table_rows(c, TRANSACTIONS[PAGE_BREAK_AFTER:], y)
    c.setFont(BOLD, SIZE)
    c.drawString(COL_DATE, y, "Total Transactions")
    c.drawRightString(NUM_RIGHT["amount"], y, total_amount())
    c.drawRightString(NUM_RIGHT["realized"], y, "532.44")
    y -= 30
    c.setFont(BOLD, 9)
    c.drawString(LEFT, y, "Endnotes For Your Account")
    y -= 12
    c.setFont(FONT, 6)
    c.drawString(
        LEFT, y, "Z Bank Sweep: Deposits are held at Schwab Bank, SSB. Interest 01/01-01/31: 0.45%."
    )
    footer(c, 3)


def main() -> None:
    c = canvas.Canvas(str(OUTPUT), pagesize=letter, invariant=1)
    c.setTitle("Schwab One Account Statement (synthetic)")
    c.setAuthor("statement2csv test fixture")
    for draw in (page1, page2, page3):
        draw(c)
        c.showPage()
    c.save()
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
