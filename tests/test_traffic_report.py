"""Tests for traffic_report.py: who counts as a net visitor."""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import traffic_report as T  # noqa: E402

PC = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
PHONE = "Mozilla/5.0 (Linux; Android 16; SM-S937N Build/BP4A.251205.006; wv) AppleWebKit/537.36 Chrome/141.0 Mobile"


def row(ip, path, ua=PC, count=1, status=200, country="KR", hour="2026-11-05T03:00:00Z", **extra):
    dims = {"datetimeHour": hour, "clientIP": ip, "clientCountryName": country, "clientRequestPath": path,
            "clientRequestHTTPHost": T.HOST, "clientRequestHTTPMethodName": "GET", "userAgent": ua,
            "edgeResponseStatus": status, "verifiedBotCategory": "", "requestSource": "eyeball",
            "securityAction": "unknown"}
    dims.update(extra)
    return {"count": count, "dimensions": dims}


def browse(ip, pages, ua=PC, country="KR", hour="2026-11-05T03:00:00Z", beacon=True):
    rows = [row(ip, p, ua, country=country, hour=hour) for p in pages]
    rows += [row(ip, "/assets/app.js", ua, country=country, hour=hour)]
    if beacon:
        rows.append(row(ip, "/cdn-cgi/rum", ua, status=204, country=country, hour=hour))
    return rows


class ClassifyTests(unittest.TestCase):
    def verdicts(self, rows, owner_rows=()):
        ips = T.classify(rows, *T.owner_markers(list(owner_rows)))
        return {ip: info["verdict"] for ip, info in ips.items()}

    def test_a_reader_with_assets_and_beacon_is_human(self):
        self.assertEqual(self.verdicts(browse("1.1.1.1", ["/", "/jobs/5.html"]))["1.1.1.1"], "human")

    def test_bot_fight_mode_checks_do_not_make_a_reader_an_attacker(self):
        rows = browse("1.1.1.1", ["/"]) + [
            row("1.1.1.1", "/cdn-cgi/challenge-platform/scripts/jsd/main.js", requestSource="inBrowserChallenge")]
        self.assertEqual(self.verdicts(rows)["1.1.1.1"], "human")

    def test_owner_ip_and_owner_phone_on_another_ip(self):
        owner = [row("9.9.9.9", "/test/index.html"), row("9.9.9.9", "/", PHONE)]
        rows = browse("9.9.9.9", ["/"]) + browse("5.5.5.5", ["/"], PHONE)
        v = self.verdicts(rows, owner)
        self.assertEqual((v["9.9.9.9"], v["5.5.5.5"]), ("owner", "owner"))

    def test_generic_ua_from_owner_ip_does_not_mark_others(self):
        owner = [row("9.9.9.9", "/test/index.html", PC)]
        self.assertEqual(self.verdicts(browse("5.5.5.5", ["/"]), owner)["5.5.5.5"], "human")

    def test_probing_drops_every_request_of_that_ip(self):
        rows = browse("6.6.6.6", ["/"]) + [row("6.6.6.6", "/wp-login.php", status=404)]
        self.assertEqual(self.verdicts(rows)["6.6.6.6"], "attack")
        rows = browse("7.7.7.7", ["/"]) + [row("7.7.7.7", "/test/", status=401)]
        self.assertEqual(self.verdicts(rows)["7.7.7.7"], "attack")

    def test_bots_scrapers_and_data_centres(self):
        rows = [row("2.2.2.2", "/", "Mozilla/5.0 (compatible; bingbot/2.0)", verifiedBotCategory="Search Engine Crawler")]
        rows += [row("3.3.3.3", f"/jobs/{i}.html", country="IN") for i in range(30)]  # HTML only
        rows += browse("34.1.2.3", ["/"], country="US")  # Google Cloud
        rows += browse("8.8.4.4", ["/"], "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/60.0.3112.91 Safari/537.36", country="US")
        rows += browse("4.4.4.4", ["/"], country="DE", beacon=False)  # foreign, no beacon
        v = self.verdicts(rows)
        self.assertEqual(v["2.2.2.2"], "none")
        for ip in ("3.3.3.3", "34.1.2.3", "8.8.4.4", "4.4.4.4"):
            self.assertEqual(v[ip], "bot", ip)

    def test_summary_counts_windows_by_kst_day(self):
        rows = browse("1.1.1.1", ["/"], hour="2026-11-05T01:00:00Z")           # 11/5 KST
        rows += browse("1.1.1.2", ["/", "/jobs/1.html"], hour="2026-11-03T16:00:00Z")  # 11/4 01시 KST
        rows += browse("1.1.1.3", ["/"], hour="2026-10-30T05:00:00Z")          # 10/30
        rows += [row("2.2.2.2", "/", "Googlebot", hour="2026-11-05T01:00:00Z")]
        report = T.summarize(T.classify(rows, set(), set()), dt.date(2026, 11, 5))
        got = {w["days"]: (w["visitors"], w["pageviews"]) for w in report["windows"]}
        self.assertEqual(got, {1: (1, 1), 3: (2, 3), 7: (3, 4)})
        self.assertEqual(report["windows"][0]["noise"]["bot"], 1)
        self.assertEqual(report["daily"][-2], {"date": "2026-11-04", "visitors": 1, "pageviews": 2})
        report["generated_at"] = "2026-11-05 12:00"
        self.assertIn("최근 7일", T.render_html(report))
        self.assertIn("오늘", T.render_text(report))


if __name__ == "__main__":
    unittest.main()
