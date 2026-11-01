"""Tests for the 강사료 실수령 계산기 math (site_test_static/pay.js), run under node.

Run from the project root:  python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

PAY_JS = Path(__file__).resolve().parent.parent / "site_test_static" / "pay.js"
NODE = shutil.which("node")


def calc(rate: float, hours: float, unit: str = "week") -> dict:
    script = (f"process.stdout.write(JSON.stringify(require({json.dumps(str(PAY_JS))})"
              f".calc({rate}, {hours}, {json.dumps(unit)})))")
    return json.loads(subprocess.run([NODE, "-e", script], capture_output=True, encoding="utf-8", check=True).stdout)


@unittest.skipUnless(NODE, "node is not installed")
class PayCalcTests(unittest.TestCase):
    def test_freelance_withholds_3_3_percent(self):
        r = calc(30000, 10)
        self.assertEqual(r["gross"], 1300000)  # 30,000 × 10 × 52/12
        self.assertEqual(r["freelance"]["items"], [["소득세 3%", 39000], ["지방소득세 0.3%", 3900]])
        self.assertEqual(r["freelance"]["net"], 1257100)

    def test_employee_pays_the_worker_share(self):
        r = calc(30000, 10)
        items = dict(r["employee"]["items"])
        self.assertEqual(items["국민연금"], 61750)    # 4.75%
        self.assertEqual(items["건강보험"], 46730)    # 3.595%, 10원 미만 버림
        self.assertEqual(items["장기요양보험"], 6140)  # 건강보험료 × 13.14%
        self.assertEqual(items["고용보험"], 11700)    # 0.9%
        self.assertEqual(items["지방소득세"], items["소득세"] // 100 * 10)
        self.assertEqual(r["employee"]["net"], 1300000 - sum(items.values()))

    def test_income_tax_grows_with_pay_and_is_zero_when_low(self):
        low = dict(calc(20000, 5)["employee"]["items"])["소득세"]
        mid = dict(calc(40000, 12)["employee"]["items"])["소득세"]
        high = dict(calc(60000, 20)["employee"]["items"])["소득세"]
        self.assertEqual(low, 0)
        self.assertLess(mid, high)
        # 월 200만 원 1인 가구는 간이세액표로 약 1만9천 원: the estimate stays near it.
        tax = dict(calc(2_000_000 * 12 / 52, 1)["employee"]["items"])["소득세"]
        self.assertTrue(15000 <= tax <= 24000, tax)

    def test_pension_uses_the_income_ceiling(self):
        items = dict(calc(200000, 40)["employee"]["items"])  # 월 3,466만 원
        self.assertEqual(items["국민연금"], 313020)  # 6,590,000 × 4.75%

    def test_under_sixty_hours_a_month_is_flagged(self):
        self.assertTrue(calc(35000, 12)["underSixty"])   # 52시간
        self.assertFalse(calc(35000, 14)["underSixty"])  # 60.7시간

    def test_monthly_hours_are_used_as_given(self):
        r = calc(30000, 40, "month")
        self.assertEqual((r["gross"], r["monthlyHours"], r["unit"]), (1200000, 40, "month"))
        self.assertTrue(r["underSixty"])
        # 주 10시간 and 한 달 43.33…시간 are the same work.
        self.assertEqual(calc(30000, 10 * 52 / 12, "month")["gross"], calc(30000, 10)["gross"])
        self.assertEqual(calc(30000, 10, "bogus")["unit"], "week")

    def test_one_week_is_one_month_over_4_33_weeks(self):
        r = calc(30000, 10)
        self.assertEqual((r["weeklyHours"], r["weekGross"]), (10, 300000))
        self.assertEqual(r["freelance"]["weekNet"], 290100)  # 1,257,100 ÷ 4.33…, 10원 미만 버림
        self.assertEqual(r["employee"]["weekNet"], r["employee"]["net"] * 12 // 52 // 10 * 10)
        self.assertEqual(calc(30000, 52, "month")["weeklyHours"], 12)

    def test_empty_input_is_zero(self):
        r = calc(0, 0)
        self.assertEqual((r["gross"], r["freelance"]["net"], r["employee"]["net"]), (0, 0, 0))
        self.assertFalse(r["underSixty"])


if __name__ == "__main__":
    unittest.main()
