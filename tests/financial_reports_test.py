"""Unit tests for the Accounting financial-report arithmetic (standard library only).

Run from the project root:   python tests/financial_reports_test.py
The expected figures are the totals printed on the reference report templates.
"""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import financial_reports as fr  # noqa: E402


class Form(dict):
    def getlist(self, key):
        return self.get(key, [])


def totals(kind, year):
    data = fr.default_data(kind, year, sample=True)
    return fr.compute(kind, year, data)


class SampleTotals(unittest.TestCase):
    def test_balance_sheet_balances(self):
        t = totals("balance_sheet", 2024)["totals"]
        self.assertEqual(t["ta"], [Decimal("32700000"), Decimal("29600000")])
        self.assertEqual(t["tle"], t["ta"])

    def test_income_statement(self):
        t = totals("income_statement", 2024)["totals"]
        self.assertEqual(t["gross"][0], Decimal("6000000"))
        self.assertEqual(t["net"][0], Decimal("3500000"))

    def test_cash_flow(self):
        t = totals("cash_flow", 2024)["totals"]
        self.assertEqual(t["opnet"][0], Decimal("5250000"))
        self.assertEqual(t["net"][0], Decimal("4250000"))

    def test_equity(self):
        r = totals("equity", 2023)
        self.assertEqual(r["totals"]["close"], [Decimal("5500000"), Decimal("4000000")])
        self.assertEqual(r["extra"]["close"], Decimal("9500000"))

    def test_budget_and_difference(self):
        r = totals("budget", 2024)
        self.assertEqual(r["totals"]["net"], [Decimal("1730000"), Decimal("1820000")])
        self.assertEqual(r["extra"]["net"], Decimal("-90000"))

    def test_monthly_budget(self):
        r = totals("monthly_budget", 2024)
        self.assertEqual(r["totals"]["exp"][0], Decimal("80000"))
        self.assertEqual(r["extra"]["exp"], Decimal("1361000"))


class Parsing(unittest.TestCase):
    def test_amount_formats(self):
        self.assertEqual(fr.parse_amount("1,200"), Decimal("1200.00"))
        self.assertEqual(fr.parse_amount("(1,200)"), Decimal("-1200.00"))
        self.assertEqual(fr.parse_amount("₱ 1,200.505"), Decimal("1200.51"))
        self.assertEqual(fr.parse_amount(""), Decimal("0.00"))

    def test_rejects_bad_amounts(self):
        for bad in ("abc", "1e999", "NaN", "Infinity", "99999999999999"):
            with self.assertRaises(ValueError, msg=bad):
                fr.parse_amount(bad)

    def test_incomplete_form_is_refused(self):
        with self.assertRaises(ValueError):
            fr.parse_form("income_statement", 2026, Form({"label__rev": ["Revenue"]}))

    def test_round_trip(self):
        data = fr.default_data("budget", 2024, sample=True)
        again = fr.loads("budget", 2024, fr.dumps(data))
        self.assertEqual(fr.compute("budget", 2024, again)["totals"], fr.compute("budget", 2024, data)["totals"])

    def test_damaged_json_falls_back_to_blank_template(self):
        data = fr.loads("balance_sheet", 2024, "{not json")
        self.assertEqual(fr.compute("balance_sheet", 2024, data)["totals"]["ta"], [Decimal("0"), Decimal("0")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
