"""Generate ``fidelity_statement.pdf``: a SYNTHETIC Fidelity monthly INVESTMENT REPORT.

All names, addresses, account numbers and amounts are fake. The layout imitates the
publicly known Fidelity brokerage statement:

* page 1: "INVESTMENT REPORT" with the period, holder + address, account number, an
  Account Summary and an Income Summary (values with $ and commas: NOT activities);
* every page: footer with "Fidelity Brokerage Services LLC, Member NYSE, SIPC" and
  "Page N of M"; pages 2+ repeat a short header (holder, account number,
  "INVESTMENT REPORT", period);
* page 2: Holdings (Core Account, Stocks, Exchange Traded Products, Mutual Funds), then
  "Activity" with the start of "Securities Bought & Sold";
* page 3: "Activity (continued)" / "Securities Bought & Sold (continued)" with repeated
  column headers, then "Dividends, Interest & Other Income", "Deposits", "Withdrawals";
* page 4: "Fees and Charges", "Other Activity In", "Core Fund Activity" (money-market
  sweep bookkeeping, must be ignored), then "Estimated Cash Flow" (end of Activity).

Every Activity subsection ends with total rows (ignored by the parser). Column headers
are two lines where labels are long ("Settlement" over "Date", "Symbol/" over "CUSIP",
"Transaction" over "Cost"). Empty numeric cells print "-". Security names wider than the
column wrap onto a second line.

Run:  .venv/bin/python tests/fixtures/generate_fidelity.py
Output is deterministic (``invariant=1``): re-running gives a byte-identical PDF.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

OUTPUT = Path(__file__).with_name("fidelity_statement.pdf")

# --------------------------------------------------------------------------------------
# Statement data (all synthetic). Test authors: derive expected activities from here.
# Every expected activity has currency "USD" and account None.
# --------------------------------------------------------------------------------------

HOLDER = "Jane Doe"
ADDRESS = ["123 EXAMPLE STREET APT 4", "ANYTOWN CA 90000-0000"]
ACCOUNT_NUMBER = "Z00-123456"
PERIOD = "February 1, 2024 - February 29, 2024"  # -> 2024-02-01 .. 2024-02-29 (leap year)

# Page 1 lines that must NOT become activities.
ACCOUNT_SUMMARY = [
    # label, this period, year-to-date
    ("Beginning Account Value", "$118,002.10", "$112,345.67"),
    ("Additions", "26,500.00", "31,500.00"),
    ("Deposits", "26,500.00", "31,500.00"),
    ("Subtractions", "-3,522.04", "-4,022.04"),
    ("Withdrawals", "-3,500.00", "-4,000.00"),
    ("Transaction Costs, Fees & Charges", "-22.04", "-22.04"),
    ("Change in Investment Value", "5,379.63", "6,535.10"),
    ("Ending Account Value", "$146,359.69", "$146,359.69"),
]
INCOME_SUMMARY = [
    ("Taxable Dividends", "176.21", "301.48"),
    ("Taxable Interest", "128.21", "130.00"),
    ("Long-Term Cap Gain", "12.34", "12.34"),
    ("Total", "$316.76", "$443.82"),
]

# Holdings page (page 2). Not activities. SCHD is here so that the Schwab detector's
# "no cross-match" behaviour is testable.
HOLDINGS = {
    # section: [(description, quantity, price per unit, ending market value, cost basis)]
    "Core Account": [
        (
            "FIDELITY GOVERNMENT MONEY MARKET (SPAXX)",
            "13,640.580",
            "$1.0000",
            "$13,640.58",
            "not applicable",
        ),
    ],
    "Stocks": [
        ("APPLE INC (AAPL)", "16.500", "$180.7500", "$2,982.38", "$2,950.12"),
        ("MICROSOFT CORP (MSFT)", "21.750", "$413.6400", "$8,996.67", "$6,100.00"),
        ("NOVARTIS AG SPON ADR (NVS)", "40.000", "$101.1200", "$4,044.80", "$3,800.00"),
        ("NVIDIA CORP (NVDA)", "12.345", "$791.1200", "$9,766.38", "$8,024.25"),
    ],
    "Exchange Traded Products": [
        (
            "VANGUARD TOTAL STOCK MARKET ETF (VTI)",
            "200.000",
            "$249.0800",
            "$49,816.00",
            "$46,512.00",
        ),
        ("SCHWAB US DIVIDEND EQUITY ETF (SCHD)", "300.400", "$77.4100", "$23,253.96", "$21,900.00"),
    ],
    "Mutual Funds": [
        (
            "EXAMPLE GLOBAL INFRASTRUCTURE INCOME FUND CL I (99999X105)",
            "1,991.123",
            "$16.9500",
            "$33,749.53",
            "$31,002.00",
        ),
    ],
}
TOTAL_HOLDINGS = "$146,250.30"

# Activity tables. Cells are the exact printed strings. Rows are printed in this order.
# fmt: off

# "Securities Bought & Sold":
#   (settlement date, security name, symbol/CUSIP, description,
#    quantity, price, transaction cost, amount)
TRADES = [
    # -> BUY 2024-02-02 AAPL qty 10.5 price 185.20 fee 4.95 amount 1949.55
    #    comment "You Bought: APPLE INC"
    ("02/02", "APPLE INC", "AAPL", "You Bought",
     "10.500", "$185.2000", "$4.95", "-1,949.55"),
    # -> BUY 2024-02-05 VTI qty 50 price 236.12 fee 0 amount 11806.00
    #    (security name wraps: "VANGUARD TOTAL STOCK MARKET" / "ETF")
    ("02/05", "VANGUARD TOTAL STOCK MARKET ETF", "VTI", "You Bought",
     "50.000", "$236.1200", "-", "-11,806.00"),
    # -> BUY 2024-02-07 99999X105 (CUSIP, no ticker) qty 125.125 price 16 fee 0
    #    amount 2002.00 (security name wraps onto three lines)
    ("02/07", "EXAMPLE GLOBAL INFRASTRUCTURE INCOME FUND CL I", "99999X105", "You Bought",
     "125.125", "$16.0000", "-", "-2,002.00"),
]
TRADES_PAGE_BREAK_AFTER = len(TRADES)  # the rows below are on page 3 ("(continued)")
TRADES += [
    # -> SELL 2024-02-09 MSFT qty 8.25 price 375.40 fee 0.07 amount 3096.98
    ("02/09", "MICROSOFT CORP", "MSFT", "You Sold",
     "-8.250", "$375.4000", "$0.07", "3,096.98"),
    # -> SELL 2024-02-20 AAPL qty 4 price 190.10 fee 0.02 amount 760.38
    ("02/20", "APPLE INC", "AAPL", "You Sold",
     "-4.000", "$190.1000", "$0.02", "760.38"),
    # -> BUY 2024-02-22 NVDA qty 12.345 price 650 fee 0 amount 8024.25
    #    (parenthesised negative amount)
    ("02/22", "NVIDIA CORP", "NVDA", "You Bought",
     "12.345", "$650.0000", "-", "(8,024.25)"),
]

# "Dividends, Interest & Other Income (Includes dividend reinvestment)":
#   (settlement date, security name, symbol/CUSIP, description, quantity, price, amount)
INCOME = [
    # -> DIVIDEND 2024-02-15 VTI amount 45.67
    #    (security name wraps), comment "Dividend Received: VANGUARD TOTAL STOCK MARKET ETF"
    ("02/15", "VANGUARD TOTAL STOCK MARKET ETF", "VTI", "Dividend Received",
     "-", "-", "45.67"),
    # -> DIVIDEND 2024-02-16 NVS amount 88.20
    ("02/16", "NOVARTIS AG SPON ADR", "NVS", "Dividend Received",
     "-", "-", "88.20"),
    # -> TAX 2024-02-16 NVS amount 13.23
    ("02/16", "NOVARTIS AG SPON ADR", "NVS", "Foreign Tax Paid",
     "-", "-", "-13.23"),
    # -> DIVIDEND 2024-02-21 99999X105 amount 12.34 (capital gain distribution -> DIVIDEND)
    ("02/21", "EXAMPLE GLOBAL INFRASTRUCTURE INCOME FUND CL I", "99999X105",
     "Long-Term Cap Gain", "-", "-", "12.34"),
    # -> DIVIDEND 2024-02-26 SCHD amount 42.34 (cash leg of a dividend reinvestment)
    ("02/26", "SCHWAB US DIVIDEND EQUITY ETF", "SCHD", "Dividend Received",
     "-", "-", "42.34"),
    # -> BUY 2024-02-26 SCHD qty 0.552 price 76.70 fee 0 amount 42.34
    #    (share leg of the reinvestment; 0.552 x 76.70 = 42.3384, printed amount wins),
    #    comment "Reinvestment: SCHWAB US DIVIDEND EQUITY ETF"
    ("02/26", "SCHWAB US DIVIDEND EQUITY ETF", "SCHD", "Reinvestment",
     "0.552", "$76.7000", "-42.34"),
    # -> INTEREST 2024-02-29 912797ZZ1 (CUSIP) amount 125.00
    ("02/29", "UNITED STATES TREAS BILLS ZERO CPN", "912797ZZ1", "Interest Earned",
     "-", "-", "125.00"),
    # -> INTEREST 2024-02-29 no symbol, amount 3.21 (blank security and symbol cells)
    ("02/29", "", "", "Interest Earned",
     "-", "-", "3.21"),
]

# "Deposits": (date, reference, description, amount)
DEPOSITS = [
    # -> DEPOSIT 2024-02-01 amount 25000.00, comment "Electronic Funds Transfer Received"
    ("02/01", "", "Electronic Funds Transfer Received", "25,000.00"),
    # -> DEPOSIT 2024-02-12 amount 1500.00, comment "Check Received (1001)"
    ("02/12", "1001", "Check Received", "1,500.00"),
]

# "Withdrawals": (date, reference, description, amount)
WITHDRAWALS = [
    # -> WITHDRAWAL 2024-02-23 amount 2500.00
    ("02/23", "", "Electronic Funds Transfer Paid", "-2,500.00"),
    # -> WITHDRAWAL 2024-02-27 amount 1000.00
    ("02/27", "", "Wire Transfer to Bank", "-1,000.00"),
]

# "Fees and Charges": (date, description, amount)
FEES = [
    # -> FEE 2024-02-27 amount 15.00, comment "Wire Transfer Fee"
    ("02/27", "Wire Transfer Fee", "-15.00"),
]

# "Other Activity In": same columns as TRADES.
OTHER_IN = [
    # -> skipped with a warning (unsupported description, no cash amount)
    ("02/28", "VANGUARD TOTAL STOCK MARKET ETF", "VTI", "Transfer of Assets",
     "100.000", "-", "-", "-"),
]

# "Core Fund Activity": money-market sweep bookkeeping -> ALL rows IGNORED (no activities)
#   (settlement date, account type, transaction, description, quantity, price, amount,
#    balance)
CORE = [
    ("02/01", "CASH", "You Bought", "FIDELITY GOVERNMENT MONEY MARKET",
     "25,000.000", "$1.0000", "-25,000.00", "30,210.33"),
    ("02/02", "CASH", "You Sold", "FIDELITY GOVERNMENT MONEY MARKET",
     "-1,949.550", "$1.0000", "1,949.55", "28,260.78"),
    ("02/05", "CASH", "You Sold", "FIDELITY GOVERNMENT MONEY MARKET",
     "-11,806.000", "$1.0000", "11,806.00", "16,454.78"),
    ("02/09", "CASH", "You Bought", "FIDELITY GOVERNMENT MONEY MARKET",
     "3,096.980", "$1.0000", "-3,096.98", "19,551.76"),
    ("02/29", "CASH", "Reinvestment", "FIDELITY GOVERNMENT MONEY MARKET",
     "3.210", "$1.0000", "-3.21", "19,554.97"),
]
# fmt: on

# Page 4, after the Activity section: NOT activities.
ESTIMATED_CASH_FLOW = [
    ("Mar 2024", "$52.10", "$3.40"),
    ("Apr 2024", "$90.00", "$3.40"),
    ("May 2024", "$45.67", "$128.00"),
]

# --------------------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------------------

PAGE_W, PAGE_H = letter
LEFT, RIGHT = 30, PAGE_W - 30
FONT, BOLD = "Helvetica", "Helvetica-Bold"
SIZE = 7
ROW_H = 9
TOTAL_PAGES = 4
SECURITY_WIDTH = 124

# Column specs: (key, top label, bottom label, x, align). "L": text starts at x,
# "R": text ends at x (numbers). Single-line labels sit on the bottom header line.
TRADE_COLS = [
    ("date", "Settlement", "Date", 30, "L"),
    ("security", "", "Security Name", 72, "L"),
    ("symbol", "Symbol/", "CUSIP", 200, "L"),
    ("description", "", "Description", 246, "L"),
    ("quantity", "", "Quantity", 380, "R"),
    ("price", "", "Price", 436, "R"),
    ("cost", "Transaction", "Cost", 496, "R"),
    ("amount", "", "Amount", 566, "R"),
]
INCOME_COLS = [c for c in TRADE_COLS if c[0] != "cost"]
CASH_COLS = [
    ("date", "", "Date", 30, "L"),
    ("reference", "", "Reference", 72, "L"),
    ("description", "", "Description", 130, "L"),
    ("amount", "", "Amount", 566, "R"),
]
FEE_COLS = [
    ("date", "", "Date", 30, "L"),
    ("description", "", "Description", 72, "L"),
    ("amount", "", "Amount", 566, "R"),
]
CORE_COLS = [
    ("date", "Settlement", "Date", 30, "L"),
    ("account_type", "Account", "Type", 72, "L"),
    ("transaction", "", "Transaction", 108, "L"),
    ("description", "", "Description", 160, "L"),
    ("quantity", "", "Quantity", 380, "R"),
    ("price", "", "Price", 436, "R"),
    ("amount", "", "Amount", 496, "R"),
    ("balance", "", "Balance", 566, "R"),
]


def dec(text: str) -> Decimal:
    s = text.replace("$", "").replace(",", "")
    if s in ("", "-"):
        return Decimal(0)
    if s.startswith("("):
        return -Decimal(s.strip("()"))
    return Decimal(s)


def money(value: Decimal, dollar: bool = True) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}{'$' if dollar else ''}{abs(value):,.2f}"


def page_header(c: canvas.Canvas, page: int) -> float:
    """Short header of pages 2+. Returns the y where content starts."""
    c.setFont(BOLD, 9)
    c.drawString(LEFT, PAGE_H - 40, f"{HOLDER} - INDIVIDUAL")
    c.setFont(FONT, 8)
    c.drawString(LEFT, PAGE_H - 51, f"Account Number: {ACCOUNT_NUMBER}")
    c.setFont(BOLD, 9)
    c.drawRightString(RIGHT, PAGE_H - 40, "INVESTMENT REPORT")
    c.setFont(FONT, 8)
    c.drawRightString(RIGHT, PAGE_H - 51, PERIOD)
    c.line(LEFT, PAGE_H - 58, RIGHT, PAGE_H - 58)
    return PAGE_H - 78


def footer(c: canvas.Canvas, page: int) -> None:
    c.setFont(FONT, 6)
    c.drawString(
        LEFT,
        38,
        "Brokerage services provided by Fidelity Brokerage Services LLC (FBS), "
        "Member NYSE, SIPC (800-000-0000).",
    )
    c.drawString(
        LEFT,
        30,
        "Brokerage accounts carried by National Financial Services LLC (NFS), Member NYSE, SIPC.",
    )
    c.setFont(FONT, 7)
    c.drawRightString(RIGHT, 30, f"Page {page} of {TOTAL_PAGES}")


def title(c: canvas.Canvas, y: float, text: str, size: int = 9) -> float:
    c.setFont(BOLD, size)
    c.drawString(LEFT, y, text)
    return y - (16 if size > 9 else 13)


def table_header(c: canvas.Canvas, cols: list[tuple], y: float) -> float:
    """Two-line column headers. Returns the y of the first row."""
    c.setFont(BOLD, SIZE)
    for _key, top, bottom, x, align in cols:
        draw = c.drawString if align == "L" else c.drawRightString
        if top:
            draw(x, y, top)
        draw(x, y - ROW_H, bottom)
    y -= ROW_H
    c.line(LEFT, y - 3, RIGHT, y - 3)
    return y - ROW_H - 3


def table_rows(c: canvas.Canvas, cols: list[tuple], rows: list[tuple], y: float) -> float:
    c.setFont(FONT, SIZE)
    for row in rows:
        lines_used = 1
        for (key, _top, _bottom, x, align), value in zip(cols, row, strict=True):
            if not value:
                continue
            if align == "R":
                c.drawRightString(x, y, value)
                continue
            parts = simpleSplit(value, FONT, SIZE, SECURITY_WIDTH) if key == "security" else [value]
            for i, part in enumerate(parts):
                c.drawString(x, y - i * ROW_H, part)
            lines_used = max(lines_used, len(parts))
        y -= ROW_H * lines_used + 3
    return y


def total_rows(c: canvas.Canvas, totals: list[tuple[str, str]], y: float) -> float:
    c.setFont(BOLD, SIZE)
    for label, value in totals:
        c.drawString(LEFT, y, label)
        c.drawRightString(566, y, value)
        y -= ROW_H + 2
    return y - 12


def page1(c: canvas.Canvas) -> None:
    c.setFont(BOLD, 18)
    c.drawString(LEFT, PAGE_H - 50, "Fidelity")
    c.setFont(FONT, 7)
    c.drawString(LEFT, PAGE_H - 60, "INVESTMENTS")
    c.setFont(BOLD, 12)
    c.drawRightString(RIGHT, PAGE_H - 45, "INVESTMENT REPORT")
    c.setFont(FONT, 9)
    c.drawRightString(RIGHT, PAGE_H - 58, PERIOD)
    y = PAGE_H - 100
    c.setFont(FONT, 9)
    for line in [HOLDER.upper(), *ADDRESS]:
        c.drawString(LEFT, y, line)
        y -= 11
    y -= 18
    y = title(c, y, "Account Summary", 12)
    c.setFont(FONT, 8)
    c.drawString(LEFT, y, f"{HOLDER} - INDIVIDUAL")
    y -= 11
    c.drawString(LEFT, y, f"Account Number: {ACCOUNT_NUMBER}")
    y -= 16
    c.setFont(BOLD, 8)
    c.drawRightString(420, y, "This Period")
    c.drawRightString(520, y, "Year-to-Date")
    y -= 12
    c.setFont(FONT, 8)
    for label, this, ytd in ACCOUNT_SUMMARY:
        indent = 10 if label in ("Deposits", "Withdrawals") else 0
        c.drawString(LEFT + indent, y, label)
        c.drawRightString(420, y, this)
        c.drawRightString(520, y, ytd)
        y -= 11
    y -= 14
    c.setFont(FONT, 8)
    c.drawString(LEFT, y, "Account Value as of Feb 29, 2024: $146,359.69")
    y -= 24
    y = title(c, y, "Income Summary", 12)
    c.setFont(FONT, 8)
    for label, this, ytd in INCOME_SUMMARY:
        c.drawString(LEFT, y, label)
        c.drawRightString(420, y, this)
        c.drawRightString(520, y, ytd)
        y -= 11
    footer(c, 1)


def page2(c: canvas.Canvas) -> None:
    y = page_header(c, 2)
    y = title(c, y, "Holdings", 12)
    c.setFont(BOLD, SIZE)
    c.drawString(LEFT, y, "Description")
    for x, label in (
        (330, "Quantity"),
        (395, "Price Per Unit"),
        (470, "Ending Market Value"),
        (566, "Total Cost Basis"),
    ):
        c.drawRightString(x, y, label)
    y -= ROW_H + 4
    for section, rows in HOLDINGS.items():
        c.setFont(BOLD, 8)
        c.drawString(LEFT, y, section)
        y -= ROW_H + 2
        c.setFont(FONT, SIZE)
        for desc, qty, price, value, cost in rows:
            c.drawString(LEFT, y, desc)
            c.drawRightString(330, y, qty)
            c.drawRightString(395, y, price)
            c.drawRightString(470, y, value)
            c.drawRightString(566, y, cost)
            y -= ROW_H + 2
        y -= 4
    c.setFont(BOLD, SIZE)
    c.drawString(LEFT, y, "Total Holdings")
    c.drawRightString(470, y, TOTAL_HOLDINGS)
    y -= 30

    y = title(c, y, "Activity", 12)
    y = title(c, y, "Securities Bought & Sold")
    y = table_header(c, TRADE_COLS, y)
    table_rows(c, TRADE_COLS, TRADES[:TRADES_PAGE_BREAK_AFTER], y)
    footer(c, 2)


def page3(c: canvas.Canvas) -> None:
    y = page_header(c, 3)
    y = title(c, y, "Activity (continued)", 12)
    y = title(c, y, "Securities Bought & Sold (continued)")
    y = table_header(c, TRADE_COLS, y)
    y = table_rows(c, TRADE_COLS, TRADES[TRADES_PAGE_BREAK_AFTER:], y)
    bought = sum((dec(r[7]) for r in TRADES if dec(r[7]) < 0), Decimal(0))
    sold = sum((dec(r[7]) for r in TRADES if dec(r[7]) > 0), Decimal(0))
    y = total_rows(
        c,
        [
            ("Total Securities Bought", money(bought)),
            ("Total Securities Sold", money(sold)),
            ("Net Securities Bought & Sold", money(bought + sold)),
        ],
        y,
    )

    y = title(c, y, "Dividends, Interest & Other Income (Includes dividend reinvestment)")
    y = table_header(c, INCOME_COLS, y)
    y = table_rows(c, INCOME_COLS, INCOME, y)
    income = sum((dec(r[6]) for r in INCOME), Decimal(0))
    y = total_rows(c, [("Total Dividends, Interest & Other Income", money(income))], y)

    y = title(c, y, "Deposits")
    y = table_header(c, CASH_COLS, y)
    y = table_rows(c, CASH_COLS, DEPOSITS, y)
    y = total_rows(c, [("Total Deposits", money(sum(dec(r[3]) for r in DEPOSITS)))], y)

    y = title(c, y, "Withdrawals")
    y = table_header(c, CASH_COLS, y)
    y = table_rows(c, CASH_COLS, WITHDRAWALS, y)
    total_rows(c, [("Total Withdrawals", money(sum(dec(r[3]) for r in WITHDRAWALS)))], y)
    footer(c, 3)


def page4(c: canvas.Canvas) -> None:
    y = page_header(c, 4)
    y = title(c, y, "Fees and Charges")
    y = table_header(c, FEE_COLS, y)
    y = table_rows(c, FEE_COLS, FEES, y)
    y = total_rows(c, [("Total Fees and Charges", money(sum(dec(r[2]) for r in FEES)))], y)

    y = title(c, y, "Other Activity In")
    y = table_header(c, TRADE_COLS, y)
    y = table_rows(c, TRADE_COLS, OTHER_IN, y)
    y = total_rows(c, [("Total Other Activity In", "$0.00")], y)

    y = title(c, y, "Core Fund Activity")
    y = table_header(c, CORE_COLS, y)
    y = table_rows(c, CORE_COLS, CORE, y)
    core = sum((dec(r[6]) for r in CORE), Decimal(0))
    y = total_rows(c, [("Total Core Fund Activity", money(core))], y)

    y = title(c, y, "Estimated Cash Flow", 12)
    c.setFont(BOLD, SIZE)
    c.drawString(LEFT, y, "Month")
    c.drawRightString(420, y, "Bond & CD Income")
    c.drawRightString(520, y, "Stock Income")
    y -= ROW_H + 2
    c.setFont(FONT, SIZE)
    for month, bond, stock in ESTIMATED_CASH_FLOW:
        c.drawString(LEFT, y, month)
        c.drawRightString(420, y, bond)
        c.drawRightString(520, y, stock)
        y -= ROW_H + 2
    c.setFont(BOLD, SIZE)
    c.drawString(LEFT, y, "Total Estimated Cash Flow")
    c.drawRightString(520, y, "$322.57")
    y -= 30
    y = title(c, y, "Additional Information and Endnotes", 12)
    c.setFont(FONT, 6)
    c.drawString(
        LEFT, y, "Core account: FIDELITY GOVERNMENT MONEY MARKET (SPAXX). 7-day yield 4.98%."
    )
    footer(c, 4)


def main() -> None:
    c = canvas.Canvas(str(OUTPUT), pagesize=letter, invariant=1)
    c.setTitle("Fidelity Investment Report (synthetic)")
    c.setAuthor("statement2csv test fixture")
    for draw in (page1, page2, page3, page4):
        draw(c)
        c.showPage()
    c.save()
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
