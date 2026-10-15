"""Layouts, sample figures and arithmetic for the Accounting department's financial reports.

Pure Python (no Flask, no database) so the maths can be tested on its own. Every report is a
declarative layout: a list of blocks (headings, sections of editable lines, and calculated rows).
The page, the live in-browser totals and the server-side totals are all driven from the same
layout, so a total is always *calculated*, never typed.

Money is kept as ``Decimal`` and stored in the database as strings inside JSON, never as floats.
"""
import json
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("1000000000000")  # ±1 trillion is more than any school report needs
MAX_ROWS = 60
MAX_LABEL = 80
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


# ------------------------------------------------------------------ layout helpers
def head(label, band=False):
    return {"t": "head", "label": label, "band": band}


def gap():
    return {"t": "gap"}


def section(sid, label, lines, total=None, paren=False, editable=True, good=None, bold=False):
    """A group of lines. ``paren`` shows the amounts in brackets (they are subtracted); ``good`` is
    'high' or 'low' and decides which budget difference is flagged red."""
    return {"t": "section", "id": sid, "label": label, "lines": list(lines), "total": total, "paren": paren,
            "editable": editable, "good": good, "bold": bold}


def calc(cid, label, expr, grand=False, good=None):
    """A calculated row: ``expr`` is a list of (sign, id) using section totals or earlier calc rows."""
    return {"t": "calc", "id": cid, "label": label, "expr": [[s, i] for s, i in expr], "grand": grand, "good": good}


def _years(period):
    return [f"{period} (₱)", f"{int(period) - 1} (₱)"]


REPORTS = {
    "balance_sheet": {
        "title": "Balance Sheet",
        "blurb": "What the school owns (assets), owes (liabilities) and the owners' equity, this year against last year.",
        "subtitle": "Year ending 31 December {period}",
        "label_header": "Category",
        "columns": lambda p: _years(p),
        "extra": None,
        "wide": False,
        "check": {"a": "ta", "b": "tle", "label": "Assets = Liabilities + Shareholder's Equity"},
        "blocks": [
            head("Assets"),
            section("ca", "Current Assets:", ["Cash and Cash Equivalents", "Accounts Receivable", "Prepaid Expenses", "Inventory"],
                    total="Total Current Assets"),
            gap(),
            section("nca", "Non-Current Assets:", ["Property and Equipment", "Goodwill"], total="Total Non-Current Assets"),
            gap(),
            calc("ta", "Total Assets", [("+", "ca"), ("+", "nca")], grand=True),
            gap(),
            head("Liabilities"),
            section("cl", "Current Liabilities:", ["Accounts Payable", "Accrued Expenses", "Unearned Revenue"],
                    total="Total Current Liabilities"),
            gap(),
            section("ncl", "Non-Current Liabilities:", ["Long-Term Debt", "Other Long-Term Liabilities"],
                    total="Total Non-Current Liabilities"),
            gap(),
            calc("tl", "Total Liabilities", [("+", "cl"), ("+", "ncl")], grand=True),
            gap(),
            head("Shareholder's Equity"),
            section("eq", None, ["Equity Capital", "Retained Earnings"], total="Total Shareholder's Equity"),
            gap(),
            calc("tle", "Total Liabilities & Shareholder's Equity", [("+", "tl"), ("+", "eq")], grand=True),
        ],
    },
    "income_statement": {
        "title": "Income Statement",
        "blurb": "Revenue less the cost of sales and operating expenses gives the net income for the period.",
        "subtitle": "For the period ending December 31, {period}",
        "label_header": "Particulars",
        "columns": lambda p: ["Amount (₱)"],
        "extra": None,
        "wide": False,
        "blocks": [
            section("rev", "Revenue", ["Revenue"], total="Total Revenue"),
            gap(),
            section("cos", "Cost of Sales", ["Materials and Supplies", "Labor Costs", "Factory Overhead"], total="Total Cost of Sales"),
            calc("gross", "Gross Profit (Loss)", [("+", "rev"), ("-", "cos")], grand=True),
            gap(),
            section("opex", "Operating Expenses", ["Office Salaries", "Marketing and Advertising", "Depreciation", "Utilities",
                                                   "Rent Expense", "Repair and Maintenance"], total="Total Operating Expenses"),
            calc("net", "Net Income", [("+", "gross"), ("-", "opex")], grand=True),
        ],
    },
    "cash_flow": {
        "title": "Cash Flow Report",
        "blurb": "Where cash came from and where it went: operations, investing and financing.",
        "subtitle": "Consolidated results for the period December 31, {period}",
        "label_header": "Cash flow",
        "columns": lambda p: ["Amount (₱)"],
        "extra": None,
        "wide": False,
        "hint": "Subtractions are typed as positive amounts. In Investing and Financing, type cash going out with a minus sign, e.g. -2,000,000.",
        "blocks": [
            section("ops", "Cash Flow From Operations", ["Net Earnings"], editable=False),
            section("adds", "Additions to cash", ["Depreciation", "Decrease in Accounts Receivable", "Increase in Accounts Payable",
                                                  "Increase in Taxes Payable"]),
            section("subs", "Subtractions from Cash", ["Increase in Inventory"], paren=True),
            calc("opnet", "Net Cash from Operations", [("+", "ops"), ("+", "adds"), ("-", "subs")]),
            section("inv", "Cash Flow from Investing", ["Equipment"]),
            section("fin", "Cash Flow from Financing", ["Proceeds from Loans"]),
            calc("net", "Cash Flow for Fiscal Year Ended December 31, {period}", [("+", "opnet"), ("+", "inv"), ("+", "fin")], grand=True),
        ],
    },
    "equity": {
        "title": "Statement of Changes in Equity",
        "blurb": "How capital and retained earnings moved during the year, from the opening to the closing balance.",
        "subtitle": "For the Year Ended December 31, {period}",
        "label_header": "Particulars",
        "columns": lambda p: ["Capital (₱)", "Retained Earnings (₱)"],
        "extra": {"kind": "rowsum", "label": "Total (₱)"},
        "wide": False,
        "hint": "Amounts under \"Less\" are typed as positive numbers; they are subtracted automatically.",
        "blocks": [
            section("open", None, ["Opening Balance"], editable=False, bold=True),
            section("add", "Add:", ["Net Income", "Other Income", "Issue of New Capital"], editable=False),
            section("less", "Less:", ["Net Loss", "Other Loss", "Dividends", "Withdrawal of Capital"], paren=True, editable=False),
            calc("close", "Closing Balance", [("+", "open"), ("+", "add"), ("-", "less")], grand=True),
        ],
    },
    "budget": {
        "title": "Business Budget",
        "blurb": "Actual income and expenses against the budget for the year, with the difference flagged.",
        "subtitle": "{period} Budget · Actual vs. Budget",
        "label_header": "Category",
        "columns": lambda p: ["Actual (₱)", "Budget (₱)"],
        "extra": {"kind": "diff", "label": "Difference (₱)", "a": 0, "b": 1},
        "wide": False,
        "hint": "Difference = Actual − Budget. Red means unfavourable (income below budget, or expenses above budget).",
        "blocks": [
            head("INCOME", band=True),
            section("opinc", "Operating Income", ["Tuition Fees", "Miscellaneous Fees", "Other"], total="Total Operating Income", good="high"),
            gap(),
            section("nopinc", "Non-Operating Income", ["Interest Income", "Gifts Received", "Donations", "Other"],
                    total="Total Non-Operating Income", good="high"),
            gap(),
            calc("tinc", "Total INCOME", [("+", "opinc"), ("+", "nopinc")], grand=True, good="high"),
            gap(),
            head("EXPENSES", band=True),
            section("opex", "Operating Expenses", ["Accounting and Legal", "Advertising", "Depreciation", "Dues and Subscriptions",
                                                   "Insurance", "Interest Expense", "Maintenance and Repairs", "Office Supplies",
                                                   "Payroll Expenses", "Salaries and Wages", "Taxes and Licenses", "Travel",
                                                   "Utilities", "Web Hosting and Domains", "Other"],
                    total="Total Operating Expenses", good="low"),
            gap(),
            section("nrec", "Non-Recurring Expenses", ["Furniture, Equipment, Software", "Other"],
                    total="Total Non-Recurring Expenses", good="low"),
            gap(),
            calc("texp", "Total EXPENSES", [("+", "opex"), ("+", "nrec")], grand=True, good="low"),
            gap(),
            calc("nibt", "Net Income Before Taxes", [("+", "tinc"), ("-", "texp")], good="high"),
            section("tax", None, ["Income Tax Expense"], editable=False, good="low"),
            calc("net", "NET INCOME", [("+", "nibt"), ("-", "tax")], grand=True, good="high"),
        ],
    },
    "monthly_budget": {
        "title": "12-Month Business Budget",
        "blurb": "Month-by-month expense budget for the whole year with row and column totals.",
        "subtitle": "Small business budgeting · Fiscal year {period} · Amounts in ₱",
        "label_header": "Monthly Expenses",
        "columns": lambda p: list(MONTHS),
        "extra": {"kind": "rowsum", "label": "YR TOTAL"},
        "wide": True,
        "hint": "List every business expense — rent, utilities, salaries, supplies and other operating costs. Add a line for each.",
        "blocks": [
            section("exp", None, ["Salaries & Wages", "Rent", "Utilities (Electricity, Water)", "Marketing & Advertising",
                                  "Supplies & Inventory", "Transportation & Delivery", "Insurance", "Miscellaneous"], total="TOTALS"),
        ],
    },
    "projection": {
        "title": "Profit and Loss Projection",
        "blurb": "Projected revenue, costs and expenses for each month, leading to a projected net profit.",
        "subtitle": "Projection for the year {period} · Amounts in ₱",
        "label_header": "Projected",
        "columns": lambda p: list(MONTHS),
        "extra": {"kind": "rowsum", "label": "YR TOTAL"},
        "wide": True,
        "blocks": [
            section("rev", "Revenue", ["Tuition Fees", "Miscellaneous Fees", "Other Income"], total="Total Revenue", good="high"),
            gap(),
            section("cogs", "Cost of Services", ["Instructional Materials", "Laboratory Supplies", "Other Direct Costs"],
                    total="Total Cost of Services", good="low"),
            calc("gross", "Gross Profit", [("+", "rev"), ("-", "cogs")], grand=True, good="high"),
            gap(),
            section("opex", "Operating Expenses", ["Salaries & Wages", "Rent", "Utilities", "Marketing & Advertising", "Supplies",
                                                   "Other Expenses"], total="Total Operating Expenses", good="low"),
            calc("ebt", "Net Profit Before Tax", [("+", "gross"), ("-", "opex")], good="high"),
            section("tax", None, ["Income Tax"], editable=False, good="low"),
            calc("net", "Net Profit (Loss)", [("+", "ebt"), ("-", "tax")], grand=True, good="high"),
        ],
    },
}

# Sample figures taken from the reference templates. Used once to seed demo data in development.
_SAMPLE_MONTHLY = {
    "Salaries & Wages": [30, 30, 35, 38, 40, 42, 45, 47, 50, 52, 55, 60],
    "Rent": [8] * 12,
    "Utilities (Electricity, Water)": [5, 6, 6, 7, 6, 6, 7, 7, 7, 7, 7, 8],
    "Marketing & Advertising": [15, 12, 15, 20, 18, 20, 22, 25, 30, 32, 35, 40],
    "Supplies & Inventory": [10, 12, 15, 12, 10, 11, 13, 14, 15, 17, 18, 20],
    "Transportation & Delivery": [5, 5, 6, 6, 6, 7, 8, 9, 10, 10, 10, 12],
    "Insurance": [3] * 12,
    "Miscellaneous": [4, 3, 4, 5, 5, 6, 7, 8, 10, 9, 9, 11],
}

SAMPLES = {
    ("balance_sheet", 2024): {
        "ca": {"Cash and Cash Equivalents": [3500000, 2800000], "Accounts Receivable": [5200000, 4700000],
               "Prepaid Expenses": [1000000, 900000], "Inventory": [6800000, 6000000]},
        "nca": {"Property and Equipment": [15000000, 14000000], "Goodwill": [1200000, 1200000]},
        "cl": {"Accounts Payable": [4000000, 3500000], "Accrued Expenses": [1500000, 1200000], "Unearned Revenue": [2000000, 1800000]},
        "ncl": {"Long-Term Debt": [8000000, 7500000], "Other Long-Term Liabilities": [1500000, 1200000]},
        "eq": {"Equity Capital": [10000000, 9000000], "Retained Earnings": [5700000, 5400000]},
    },
    ("income_statement", 2024): {
        "rev": {"Revenue": [10000000]},
        "cos": {"Materials and Supplies": [2000000], "Labor Costs": [1500000], "Factory Overhead": [500000]},
        "opex": {"Office Salaries": [1200000], "Marketing and Advertising": [300000], "Depreciation": [200000],
                 "Utilities": [150000], "Rent Expense": [600000], "Repair and Maintenance": [50000]},
    },
    ("cash_flow", 2024): {
        "ops": {"Net Earnings": [5000000]},
        "adds": {"Depreciation": [150000], "Decrease in Accounts Receivable": [200000],
                 "Increase in Accounts Payable": [250000], "Increase in Taxes Payable": [50000]},
        "subs": {"Increase in Inventory": [400000]},
        "inv": {"Equipment": [-2000000]},
        "fin": {"Proceeds from Loans": [1000000]},
    },
    ("equity", 2023): {
        "open": {"Opening Balance": [5000000, 3000000]},
        "add": {"Net Income": [0, 1200000], "Other Income": [0, 200000], "Issue of New Capital": [1000000, 0]},
        "less": {"Dividends": [0, 400000], "Withdrawal of Capital": [500000, 0]},
    },
    ("budget", 2024): {
        "opinc": {"Tuition Fees": [3500000, 3600000], "Miscellaneous Fees": [2000000, 2000000], "Other": [500000, 600000]},
        "nopinc": {"Interest Income": [300000, 250000], "Gifts Received": [200000, 200000], "Donations": [100000, 150000],
                   "Other": [150000, 100000]},
        "opex": {"Accounting and Legal": [150000, 200000], "Advertising": [300000, 250000], "Depreciation": [120000, 100000],
                 "Dues and Subscriptions": [50000, 60000], "Insurance": [80000, 75000], "Interest Expense": [60000, 50000],
                 "Maintenance and Repairs": [100000, 120000], "Office Supplies": [40000, 50000],
                 "Payroll Expenses": [1200000, 1300000], "Salaries and Wages": [1800000, 1700000],
                 "Taxes and Licenses": [300000, 280000], "Travel": [100000, 90000], "Utilities": [250000, 270000],
                 "Web Hosting and Domains": [20000, 25000], "Other": [50000, 60000]},
        "nrec": {"Furniture, Equipment, Software": [400000, 450000]},
    },
    ("monthly_budget", 2024): {"exp": {label: [v * 1000 for v in values] for label, values in _SAMPLE_MONTHLY.items()}},
}


# ------------------------------------------------------------------ number handling
def to_decimal(value):
    try:
        return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return ZERO


def parse_amount(text):
    """'1,200', '(1,200)', '₱ 1,200.50', '-300' or '' -> Decimal. Raises ValueError when it is not a number."""
    raw = (text or "").strip().replace("₱", "").replace(",", "").replace(" ", "")
    if raw in ("", "-", "–"):
        return ZERO
    negative = raw.startswith("(") and raw.endswith(")")
    if negative:
        raw = raw[1:-1]
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"“{text.strip()}” is not a valid amount.") from None
    if not value.is_finite():
        raise ValueError(f"“{text.strip()}” is not a valid amount.")
    value = -value if negative else value
    if abs(value) > MAX_AMOUNT:
        raise ValueError("That amount is too large.")
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def fmt(value):
    """Accounting display: 1,234 / 1,234.50 / (1,234) / '-' for zero."""
    value = to_decimal(value)
    if value == 0:
        return "-"
    shown = abs(value)
    text = f"{shown:,.0f}" if shown == shown.to_integral_value() else f"{shown:,.2f}"
    return f"({text})" if value < 0 else text


def fmt_input(value):
    """What goes inside an input box: blank for zero, minus sign for negatives."""
    value = to_decimal(value)
    if value == 0:
        return ""
    shown = abs(value)
    text = f"{shown:,.0f}" if shown == shown.to_integral_value() else f"{shown:,.2f}"
    return f"-{text}" if value < 0 else text


# ------------------------------------------------------------------ data in / out
def spec_for(kind):
    return REPORTS.get(kind)


def ncols(kind, period):
    return len(REPORTS[kind]["columns"](period))


def sections_of(kind):
    return [b for b in REPORTS[kind]["blocks"] if b["t"] == "section"]


def default_data(kind, period, values=None, sample=False):
    """Blank template (or sample/pre-filled values) as {"sections": {sid: [{"label", "v": [Decimal,...]}]}}.
    ``values`` is {sid: {label: [numbers]}}; labels not in the layout are appended as extra lines."""
    n = ncols(kind, period)
    if values is None and sample:
        values = SAMPLES.get((kind, int(period)))
    values = values or {}
    out = {}
    for sec in sections_of(kind):
        wanted = values.get(sec["id"], {})
        rows = [{"label": label, "v": [to_decimal(x) for x in (wanted.get(label, []) + [0] * n)[:n]]} for label in sec["lines"]]
        if sec["editable"]:
            rows += [{"label": label, "v": [to_decimal(x) for x in (vals + [0] * n)[:n]]}
                     for label, vals in wanted.items() if label not in sec["lines"]]
        out[sec["id"]] = rows
    return {"sections": out}


def dumps(data):
    return json.dumps({"sections": {sid: [{"label": r["label"], "v": [str(to_decimal(x)) for x in r["v"]]} for r in rows]
                                    for sid, rows in data["sections"].items()}}, separators=(",", ":"))


def loads(kind, period, text):
    """Saved JSON -> data, tolerating anything missing or damaged by falling back to the blank layout."""
    base = default_data(kind, period)
    try:
        saved = json.loads(text or "{}").get("sections", {})
    except (TypeError, ValueError, AttributeError):
        return base
    n = ncols(kind, period)
    for sec in sections_of(kind):
        rows = saved.get(sec["id"])
        if not isinstance(rows, list):
            continue
        clean = []
        for row in rows[:MAX_ROWS]:
            if not isinstance(row, dict):
                continue
            values = row.get("v") if isinstance(row.get("v"), list) else []
            clean.append({"label": str(row.get("label", ""))[:MAX_LABEL],
                          "v": [to_decimal(x) for x in (values + [0] * n)[:n]]})
        if not sec["editable"]:
            if len(clean) != len(sec["lines"]):
                continue
            for row, label in zip(clean, sec["lines"]):
                row["label"] = label
        base["sections"][sec["id"]] = clean
    return base


def parse_form(kind, period, form):
    """Read the report form (parallel lists per section) into data, validating every amount."""
    n = ncols(kind, period)
    out = {}
    for sec in sections_of(kind):
        sid = sec["id"]
        labels = form.getlist(f"label__{sid}")
        columns = [form.getlist(f"v__{sid}__{c}") for c in range(n)]
        if any(len(col) != len(labels) for col in columns):
            raise ValueError("The form was incomplete. Reload the page and try again.")
        if len(labels) > MAX_ROWS:
            raise ValueError(f"A section can have at most {MAX_ROWS} lines.")
        if not sec["editable"]:
            if len(labels) != len(sec["lines"]):
                raise ValueError("The form was incomplete. Reload the page and try again.")
            labels = list(sec["lines"])
        rows = []
        for i, label in enumerate(labels):
            label = " ".join((label or "").split())
            if len(label) > MAX_LABEL:
                raise ValueError(f"A line name is too long (limit {MAX_LABEL} characters).")
            try:
                values = [parse_amount(col[i]) for col in columns]
            except ValueError as exc:
                raise ValueError(f"{label or 'A line'}: {exc}") from None
            if sec["editable"] and not label:
                if any(values):
                    raise ValueError("Give every line that has an amount a name.")
                continue  # an empty extra line: drop it
            rows.append({"label": label, "v": values})
        out[sid] = rows
    return {"sections": out}


# ------------------------------------------------------------------ arithmetic
def compute(kind, period, data):
    """Totals for every section and calculated row.
    Returns {"totals": {id: [per column]}, "extra": {id: value|None}, "line_extra": {sid: [value|None]}}."""
    spec, n = REPORTS[kind], ncols(kind, period)
    extra = spec["extra"]

    def row_extra(values):
        if not extra:
            return None
        if extra["kind"] == "rowsum":
            return sum(values, ZERO)
        return values[extra["a"]] - values[extra["b"]]

    totals, extras, line_extra = {}, {}, {}
    for block in spec["blocks"]:
        if block["t"] == "section":
            rows = data["sections"].get(block["id"], [])
            totals[block["id"]] = [sum((r["v"][c] for r in rows), ZERO) for c in range(n)]
            line_extra[block["id"]] = [row_extra(r["v"]) for r in rows]
            extras[block["id"]] = row_extra(totals[block["id"]])
        elif block["t"] == "calc":
            values = [ZERO] * n
            for sign, ref in block["expr"]:
                for c in range(n):
                    values[c] += totals[ref][c] if sign == "+" else -totals[ref][c]
            totals[block["id"]] = values
            extras[block["id"]] = row_extra(values)
    return {"totals": totals, "extra": extras, "line_extra": line_extra}


def is_unfavourable(good, difference):
    """Budget colouring: income should be high, expenses low."""
    if good is None or difference is None:
        return False
    return difference < 0 if good == "high" else difference > 0


def labels_for(kind, period):
    """Row labels with the {period} placeholder filled in."""
    return {"period": period}


def total_of(kind, period, data, calc_id, column=0):
    return compute(kind, period, data)["totals"][calc_id][column]
