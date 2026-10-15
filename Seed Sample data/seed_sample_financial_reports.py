#!/usr/bin/env python3
"""
NEPTUNE - financial report sample loader
========================================
Adds sample data for the Accounting department's Financial Reports page:

* Balance Sheet, Income Statement, Cash Flow Report, Statement of Changes in Equity,
  Business Budget and 12-Month Business Budget for 2024, 2025 and 2026
* Profit and Loss Projection for 2026 and 2027
* a Billing Statement (charges + balance forward) for each Active student

Usage (stop the Flask app first, then run from the project folder):

    python "Seed Sample data/seed_sample_financial_reports.py"                          # uses instance/student_management.db
    python "Seed Sample data/seed_sample_financial_reports.py" path/to/student_management.db
    python "Seed Sample data/seed_sample_financial_reports.py" --replace                # also refresh rows this script made before
    python "Seed Sample data/seed_sample_financial_reports.py" --students 6             # billing statements for at most 6 students

* Only the Python standard library is needed (plus this project's financial_reports.py).
* The figures are generated so they agree with each other: every Balance Sheet balances,
  each year's opening equity is the previous year's closing equity, the Cash Flow net change
  equals the change in cash on the Balance Sheet, and net income flows into Equity and Cash Flow.
  The 2024 Balance Sheet / Income Statement figures are the ones from the reference templates.
* Safe to run more than once: a report is looked up by (kind, year) first and skipped if it
  exists, so nothing you typed in the app is ever overwritten. --replace only refreshes rows
  whose "last saved by" is `sample-data` (i.e. rows written by this script).
* A timestamped backup of the database is written next to it before anything changes.
* Billing statements list the charges only; the student's recorded payments are pulled in by the
  app automatically. Statement dates use today's date.
"""
import argparse
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent   # this script lives in "Seed Sample data/"
sys.path.insert(0, str(PROJECT_ROOT))
import financial_reports as fr  # noqa: E402  (the same layouts and arithmetic the app uses)

SEED_USER = "sample-data"
PER_UNIT_TUITION = 700          # pesos per unit on a sample billing statement
MISC_FEE = 3200
LAB_FEE = 1800
DEFAULT_UNITS = 21
DEFAULT_REMIT_TO = "ASIAN INSTITUTE OF COMPUTER STUDIES\nAccounting Department\nPlease write the student number on your payment."

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS financial_report (
    id INTEGER NOT NULL PRIMARY KEY,
    kind VARCHAR(30) NOT NULL,
    period VARCHAR(30) NOT NULL,
    data TEXT NOT NULL,
    updated_by VARCHAR(50) NOT NULL,
    updated_at DATETIME NOT NULL,
    CONSTRAINT uq_financial_report_kind_period UNIQUE (kind, period)
)"""


# --------------------------------------------------------------------------- yearly figures
# Closing position at 31 Dec 2024 (the reference Balance Sheet).
STATE_2024 = {"cash": 3_500_000, "ar": 5_200_000, "prepaid": 1_000_000, "inventory": 6_800_000,
              "ppe": 15_000_000, "goodwill": 1_200_000, "ap": 4_000_000, "accrued": 1_500_000,
              "unearned": 2_000_000, "ltd": 8_000_000, "oltl": 1_500_000, "capital": 10_000_000, "re": 5_700_000}
# Equity roll-forward for 2024: 2023 closing (reference Statement of Equity) -> the 2024 closing above.
EQUITY_2024 = {"open": (5_500_000, 4_000_000), "net": 3_500_000, "other": 0, "issue": 4_500_000, "dividends": 1_800_000, "withdraw": 0}

YEAR_INPUTS = {
    2025: {
        "revenue": 11_500_000, "cos": (2_300_000, 1_700_000, 600_000),
        "opex": (1_350_000, 350_000, 220_000, 170_000, 640_000, 60_000),   # salaries, marketing, depreciation, utilities, rent, repairs
        "other_income": 150_000, "issue": 1_000_000, "dividends": 1_500_000, "withdraw": 0, "capex": 1_620_000,
        "ar": 5_600_000, "prepaid": 1_100_000, "inventory": 7_200_000,
        "ap": 4_300_000, "accrued": 1_600_000, "unearned": 2_300_000, "ltd": 7_500_000, "oltl": 1_400_000,
    },
    2026: {
        "revenue": 12_800_000, "cos": (2_550_000, 1_850_000, 650_000),
        "opex": (1_500_000, 400_000, 250_000, 180_000, 660_000, 70_000),
        "other_income": 200_000, "issue": 0, "dividends": 1_800_000, "withdraw": 0, "capex": 1_300_000,
        "ar": 6_000_000, "prepaid": 1_200_000, "inventory": 7_600_000,
        "ap": 4_500_000, "accrued": 1_700_000, "unearned": 2_600_000, "ltd": 7_000_000, "oltl": 1_300_000,
    },
}
BUDGET_GROWTH = {2025: 1.08, 2026: 1.07}
MONTHLY_GROWTH = {2025: 1.08, 2026: 1.16}

# 2026 / 2027 monthly projection (pesos), January..December. Tuition peaks at enrolment (Aug, Jan).
TUITION = {2026: [900_000, 650_000, 500_000, 450_000, 350_000, 150_000, 300_000, 1_900_000, 1_150_000, 850_000, 650_000, 500_000],
           2027: [980_000, 700_000, 540_000, 490_000, 380_000, 170_000, 330_000, 2_050_000, 1_250_000, 920_000, 700_000, 540_000]}


def money(value):
    return Decimal(value).quantize(Decimal("0.01"))


def dump(kind, year, values):
    return fr.dumps(fr.default_data(kind, year, values=values))


def check_equal(label, left, right):
    if left != right:
        raise SystemExit(f"Internal check failed ({label}): {left} != {right}")


# --------------------------------------------------------------------------- report builders
def roll_forward(year, prev, inp):
    """Closing balance sheet of ``year`` from the previous year's closing and this year's activity."""
    net = inp["revenue"] - sum(inp["cos"]) - sum(inp["opex"])
    dep = inp["opex"][2]
    state = {k: inp[k] for k in ("ar", "prepaid", "inventory", "ap", "accrued", "unearned", "ltd", "oltl")}
    state["goodwill"] = prev["goodwill"]
    state["ppe"] = prev["ppe"] + inp["capex"] - dep
    state["capital"] = prev["capital"] + inp["issue"] - inp["withdraw"]
    state["re"] = prev["re"] + net + inp["other_income"] - inp["dividends"]
    liabilities = state["ap"] + state["accrued"] + state["unearned"] + state["ltd"] + state["oltl"]
    non_cash = state["ar"] + state["prepaid"] + state["inventory"] + state["ppe"] + state["goodwill"]
    state["cash"] = liabilities + state["capital"] + state["re"] - non_cash   # cash is what makes the sheet balance
    if state["cash"] <= 0:
        raise SystemExit(f"Sample figures for {year} leave no cash; adjust YEAR_INPUTS.")
    return state, net


def balance_sheet(year, cur, prev):
    pair = lambda key: [cur[key], prev[key]]  # noqa: E731
    return dump("balance_sheet", year, {
        "ca": {"Cash and Cash Equivalents": pair("cash"), "Accounts Receivable": pair("ar"),
               "Prepaid Expenses": pair("prepaid"), "Inventory": pair("inventory")},
        "nca": {"Property and Equipment": pair("ppe"), "Goodwill": pair("goodwill")},
        "cl": {"Accounts Payable": pair("ap"), "Accrued Expenses": pair("accrued"), "Unearned Revenue": pair("unearned")},
        "ncl": {"Long-Term Debt": pair("ltd"), "Other Long-Term Liabilities": pair("oltl")},
        "eq": {"Equity Capital": pair("capital"), "Retained Earnings": pair("re")}})


def income_statement(year, inp):
    cos, opex = inp["cos"], inp["opex"]
    return dump("income_statement", year, {
        "rev": {"Revenue": [inp["revenue"]]},
        "cos": dict(zip(["Materials and Supplies", "Labor Costs", "Factory Overhead"], ([c] for c in cos))),
        "opex": dict(zip(["Office Salaries", "Marketing and Advertising", "Depreciation", "Utilities", "Rent Expense",
                          "Repair and Maintenance"], ([c] for c in opex)))})


def equity_statement(year, opening, net, other, issue, dividends, withdraw):
    return dump("equity", year, {
        "open": {"Opening Balance": list(opening)},
        "add": {"Net Income": [0, net], "Other Income": [0, other], "Issue of New Capital": [issue, 0]},
        "less": {"Dividends": [0, dividends], "Withdrawal of Capital": [withdraw, 0]}})


def cash_flow(year, prev, cur, inp, net):
    """Cash flow derived from the two balance sheets, so Net change in cash == change in the cash balance."""
    adds, subs = {"Depreciation": [inp["opex"][2]]}, {}
    if inp["other_income"]:
        adds["Other income received"] = [inp["other_income"]]
    for key, label, asset in (("ar", "Accounts Receivable", True), ("prepaid", "Prepaid Expenses", True),
                              ("inventory", "Inventory", True), ("ap", "Accounts Payable", False),
                              ("accrued", "Accrued Expenses", False), ("unearned", "Unearned Revenue", False)):
        delta = cur[key] - prev[key]
        if not delta:
            continue
        increase = delta > 0
        (subs if increase == asset else adds)[f"{'Increase' if increase else 'Decrease'} in {label}"] = [abs(delta)]
    debt = (cur["ltd"] + cur["oltl"]) - (prev["ltd"] + prev["oltl"])
    fin = {}
    if debt > 0:
        fin["Proceeds from Loans"] = [debt]
    elif debt < 0:
        fin["Repayment of long-term debt"] = [debt]
    if inp["issue"]:
        fin["Proceeds from issue of new capital"] = [inp["issue"]]
    if inp["dividends"]:
        fin["Dividends paid"] = [-inp["dividends"]]
    if inp["withdraw"]:
        fin["Withdrawal of capital"] = [-inp["withdraw"]]
    values = {"ops": {"Net Earnings": [net]}, "adds": adds, "subs": subs, "inv": {"Equipment": [-inp["capex"]]}, "fin": fin}
    data = dump("cash_flow", year, values)
    result = fr.compute("cash_flow", year, fr.loads("cash_flow", year, data))
    check_equal(f"cash flow {year} equals change in cash", result["totals"]["net"][0], money(cur["cash"] - prev["cash"]))
    return data


def budget(year, previous_budget, actual_noise):
    """Budget = last year's budget x growth. Actuals are budget +/- a few percent (left blank for the open year)."""
    rng = random.Random(f"budget-{year}")
    values, new_budget = {}, {}
    for sid, rows in previous_budget.items():
        values[sid], new_budget[sid] = {}, {}
        for label, (_actual, planned) in rows.items():
            target = round(planned * BUDGET_GROWTH[year], -3)
            actual = round(target * rng.uniform(0.94, 1.06), -3) if actual_noise else 0
            values[sid][label] = [actual, target]
            new_budget[sid][label] = (actual, target)
    return dump("budget", year, values), new_budget


def monthly_budget(year):
    growth = 1.0 if year == 2024 else MONTHLY_GROWTH[year]
    rows = {label: [round(v * 1000 * growth, -2) for v in months] for label, months in fr._SAMPLE_MONTHLY.items()}
    rows["Internet & Software Subscriptions"] = [round(4_500 * growth, -2)] * 12
    return dump("monthly_budget", year, {"exp": rows})


def projection(year):
    rng = random.Random(f"projection-{year}")
    tuition = TUITION[year]
    misc = [round(t * 0.18, -2) for t in tuition]
    other = [rng.choice([8_000, 10_000, 12_000, 15_000]) for _ in range(12)]
    materials = [round(t * 0.07, -2) for t in tuition]
    lab = [round(t * 0.04, -2) for t in tuition]
    direct = [round(t * 0.03, -2) for t in tuition]
    scale = 1.0 if year == 2026 else 1.06
    salaries = [round(520_000 * scale, -3)] * 12
    rent = [round(55_000 * scale, -3)] * 12
    utilities = [round(rng.uniform(21_000, 30_000) * scale, -3) for _ in range(12)]
    marketing = [round((60_000 if m in (4, 5, 6, 7) else 22_000) * scale, -3) for m in range(12)]
    supplies = [round(rng.uniform(14_000, 24_000) * scale, -3) for _ in range(12)]
    other_exp = [round(rng.uniform(9_000, 16_000) * scale, -3) for _ in range(12)]
    revenue = [t + m + o for t, m, o in zip(tuition, misc, other)]
    gross = [r - a - b - c for r, a, b, c in zip(revenue, materials, lab, direct)]
    ebt = [g - sum(x) for g, x in zip(gross, zip(salaries, rent, utilities, marketing, supplies, other_exp))]
    tax = [round(max(0, e) * 0.25, -2) for e in ebt]     # 25% on profitable months
    return dump("projection", year, {
        "rev": {"Tuition Fees": tuition, "Miscellaneous Fees": misc, "Other Income": other},
        "cogs": {"Instructional Materials": materials, "Laboratory Supplies": lab, "Other Direct Costs": direct},
        "opex": {"Salaries & Wages": salaries, "Rent": rent, "Utilities": utilities, "Marketing & Advertising": marketing,
                 "Supplies": supplies, "Other Expenses": other_exp},
        "tax": {"Income Tax": tax}})


def build_all():
    """Every yearly report as {(kind, year): json}, built so the years agree with each other."""
    out = {}
    # 2024 and earlier: the reference templates (plus the equity roll-forward that ties 2023 to 2024).
    for (kind, year), _values in fr.SAMPLES.items():
        out[(kind, year)] = fr.dumps(fr.default_data(kind, year, sample=True))
    e = EQUITY_2024
    out[("equity", 2024)] = equity_statement(2024, e["open"], e["net"], e["other"], e["issue"], e["dividends"], e["withdraw"])
    closing = fr.compute("equity", 2024, fr.loads("equity", 2024, out[("equity", 2024)]))["totals"]["close"]
    check_equal("2024 equity closing = balance sheet", closing, [money(STATE_2024["capital"]), money(STATE_2024["re"])])
    check_equal("2024 income statement net", fr.compute("income_statement", 2024, fr.default_data("income_statement", 2024, sample=True))["totals"]["net"][0],
                money(e["net"]))
    out[("monthly_budget", 2024)] = monthly_budget(2024)

    previous, previous_budget = STATE_2024, fr.SAMPLES[("budget", 2024)]
    previous_budget = {sid: {label: (v[0], v[1]) for label, v in rows.items()} for sid, rows in previous_budget.items()}
    previous_closing = (STATE_2024["capital"], STATE_2024["re"])
    for year, inp in YEAR_INPUTS.items():
        state, net = roll_forward(year, previous, inp)
        out[("balance_sheet", year)] = balance_sheet(year, state, previous)
        sheet = fr.compute("balance_sheet", year, fr.loads("balance_sheet", year, out[("balance_sheet", year)]))["totals"]
        check_equal(f"{year} balance sheet balances", sheet["ta"][0], sheet["tle"][0])
        out[("income_statement", year)] = income_statement(year, inp)
        out[("equity", year)] = equity_statement(year, previous_closing, net, inp["other_income"], inp["issue"], inp["dividends"], inp["withdraw"])
        eq_close = fr.compute("equity", year, fr.loads("equity", year, out[("equity", year)]))["totals"]["close"]
        check_equal(f"{year} equity closing = balance sheet", eq_close, [money(state["capital"]), money(state["re"])])
        out[("cash_flow", year)] = cash_flow(year, previous, state, inp, net)
        out[("budget", year)], previous_budget = budget(year, previous_budget, actual_noise=(year != 2026))
        out[("monthly_budget", year)] = monthly_budget(year)
        previous, previous_closing = state, (state["capital"], state["re"])
    for year in (2026, 2027):
        out[("projection", year)] = projection(year)
    return out


# --------------------------------------------------------------------------- billing statements
def statement_json(student, units, has_lab, today, index):
    enrol = date(today.year, 8, 3) if today >= date(today.year, 8, 3) else date(today.year - 1, 8, 3)
    charges = [{"date": enrol.isoformat(), "description": f"Tuition - {units} units x PHP {PER_UNIT_TUITION:,} (1st Sem {enrol.year}-{enrol.year + 1})",
                "amount": str(money(units * PER_UNIT_TUITION))},
               {"date": enrol.isoformat(), "description": "Miscellaneous fees", "amount": str(money(MISC_FEE))}]
    if has_lab:
        charges.append({"date": enrol.isoformat(), "description": "Laboratory fee", "amount": str(money(LAB_FEE))})
    if index % 4 == 1:
        charges.append({"date": (enrol + timedelta(days=45)).isoformat(), "description": "Late enrolment surcharge", "amount": "500.00"})
    forward = [0, 2_500, 0, 1_200, 0, 3_000][index % 6]
    return {"forward": str(money(forward)), "statement_date": today.isoformat(),
            "due_date": (today + timedelta(days=30)).isoformat(), "remit_to": DEFAULT_REMIT_TO, "charges": charges}


def load_statements(db, limit, today):
    """One statement per Active student: tuition from the units of their curriculum year / 1st semester."""
    import json
    students = db.execute("SELECT id, student_number, first_name, last_name, course, year_level FROM student "
                          "WHERE status = 'Active' ORDER BY student_number LIMIT ?", (limit,)).fetchall()
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    has_curriculum = {"curriculum_program", "curriculum_course"} <= tables
    out = {}
    for index, s in enumerate(students):
        units, has_lab = DEFAULT_UNITS, False
        if has_curriculum:
            rows = db.execute("SELECT c.units, c.code FROM curriculum_course c JOIN curriculum_program p ON p.id = c.program_id "
                              "WHERE p.name = ? AND c.year = ? AND c.term = 'First Semester'", (s["course"], s["year_level"])).fetchall()
            if rows:
                units = sum(r["units"] for r in rows)
                has_lab = any(r["code"].strip().upper().endswith(" L") for r in rows)
        out[s["student_number"]] = json.dumps(statement_json(s, units, has_lab, today, index), separators=(",", ":"))
    return out


# --------------------------------------------------------------------------- database
def backup(path):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.{stamp}.before-sample-financial.bak")
    src, dst = sqlite3.connect(path), sqlite3.connect(target)
    with dst:
        src.backup(dst)   # safe even while the database is in WAL mode
    src.close()
    dst.close()
    return target


def main():
    parser = argparse.ArgumentParser(description="Load sample Financial Reports into the NEPTUNE database.")
    parser.add_argument("db", nargs="?", default=str(PROJECT_ROOT / "instance" / "student_management.db"))
    parser.add_argument("--replace", action="store_true", help="refresh rows previously written by this script")
    parser.add_argument("--students", type=int, default=10, help="how many Active students get a billing statement (default 10)")
    args = parser.parse_args()
    path = Path(args.db)
    if not path.exists():
        raise SystemExit(f"Database not found: {path}\nRun the app once (python app.py) so it creates the database, then try again.")

    reports = build_all()
    print(f"Backup saved: {backup(path)}")
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute(CREATE_TABLE)
    stamp = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f")
    statements = load_statements(db, max(0, args.students), date.today()) if args.students else {}

    added = replaced = skipped = 0
    rows = [(kind, str(year), data) for (kind, year), data in sorted(reports.items(), key=lambda kv: (kv[0][1], kv[0][0]))]
    rows += [("billing_statement", number, data) for number, data in statements.items()]
    for kind, period, data in rows:
        existing = db.execute("SELECT id, updated_by FROM financial_report WHERE kind = ? AND period = ?", (kind, period)).fetchone()
        if existing is None:
            db.execute("INSERT INTO financial_report (kind, period, data, updated_by, updated_at) VALUES (?,?,?,?,?)",
                       (kind, period, data, SEED_USER, stamp))
            added += 1
        elif args.replace and existing["updated_by"] in (SEED_USER, "system"):
            db.execute("UPDATE financial_report SET data = ?, updated_by = ?, updated_at = ? WHERE id = ?",
                       (data, SEED_USER, stamp, existing["id"]))
            replaced += 1
        else:
            skipped += 1
    db.commit()
    db.close()

    if not (added or replaced):
        print("\nNothing to add - the sample financial reports are already present.")
    else:
        print(f"\nAdded {added} report(s), refreshed {replaced}, left {skipped} existing one(s) untouched.")
        print(f"  Yearly reports : {len(reports)} (2024-2026 statements and budgets, 2026-2027 projections)")
        print(f"  Billing statements: {len(statements)} (one per Active student, charges only)")
    print("\nOpen Accounting > Financial Reports to see them.")


if __name__ == "__main__":
    main()
