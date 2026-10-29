"""Tests for the static site builder.

Run from the project root:  python -m unittest discover -s tests
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_site as bs  # noqa: E402
import collect_jobs as cj  # noqa: E402
from test_collector import make_job  # noqa: E402

TODAY = dt.date(2026, 10, 29)
BUILT_AT = dt.datetime(2026, 10, 29, 7, 0, tzinfo=bs.KST)


def seed(db_path: Path) -> None:
    conn = cj.init_db(db_path)
    cj.save_job(conn, make_job(title="아주대 강사 모집", deadline="2026-11-06", original_url="https://a.example/1"))
    cj.save_job(conn, make_job(
        title='<script>alert("x")</script> 강사', institution_name="세종학당재단", deadline="rolling",
        original_url="javascript:alert(1)",
    ))
    cj.save_job(conn, make_job(title="이미 마감", deadline="2026-10-01", original_url="https://a.example/3"))
    cj.save_job(conn, make_job(title="반려된 공고", deadline="2026-12-01", original_url="https://a.example/4"))
    cj.save_job(conn, make_job(title="중복 공고", deadline="2026-12-02", original_url="https://a.example/5"))
    cj.save_job(conn, make_job(
        title="Lecturer of Korean", institution_name="Smith College", location_text="미국",
        deadline="2026-12-01", original_url="https://a.example/6",
    ))
    conn.execute("UPDATE jobs SET status = 'rejected' WHERE title = '반려된 공고'")
    conn.execute("UPDATE jobs SET is_canonical = 0 WHERE title = '중복 공고'")
    conn.execute(
        "UPDATE jobs SET latitude = 37.28, longitude = 127.04, address = '경기 수원시 영통구', demo_lesson = 1 "
        "WHERE title = '아주대 강사 모집'"
    )
    conn.execute("UPDATE jobs SET is_overseas = 1, country = '미국' WHERE title = 'Lecturer of Korean'")
    conn.commit()
    conn.close()


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.db = base / "jobs.sqlite3"
        self.out = base / "site"
        seed(self.db)
        self.config = {"site_url": "https://jobs.example", "kakao_js_key": "KEY", "alert_endpoint": None, "adsense_client": None}
        self.stats = bs.build(self.db, self.out, self.config, TODAY, BUILT_AT)
        self.index = (self.out / "index.html").read_text(encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def job_page(self, title_fragment: str) -> str:
        for page in (self.out / "jobs").glob("*.html"):
            text = page.read_text(encoding="utf-8")
            if title_fragment in text:
                return text
        self.fail(f"no job page containing {title_fragment!r}")

    def test_only_live_canonical_unrejected_jobs_publish(self):
        self.assertEqual(self.stats["jobs"], 3)
        self.assertNotIn("이미 마감", self.index)
        self.assertNotIn("반려된 공고", self.index)
        self.assertNotIn("중복 공고", self.index)
        self.assertEqual(len(list((self.out / "jobs").glob("*.html"))), 3)

    def test_untrusted_text_is_escaped(self):
        self.assertNotIn('<script>alert("x")</script>', self.index)
        self.assertIn("&lt;script&gt;", self.index)

    def test_non_http_links_are_never_linked(self):
        page = self.job_page("&lt;script&gt;")
        self.assertNotIn("javascript:alert", page)
        self.assertIn("원문 링크를 확인하지 못했어요", page)

    def test_job_page_has_valid_job_posting(self):
        page = self.job_page("아주대 강사 모집")
        raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1)
        data = json.loads(raw)
        self.assertEqual(data["@type"], "JobPosting")
        self.assertEqual(data["validThrough"], "2026-11-06T23:59:59+09:00")
        self.assertEqual(data["jobLocation"]["address"]["addressCountry"], "KR")
        self.assertIn("data-mini-map", page)
        self.assertIn("모의수업이 있는 공고예요", page)

    def test_map_rows_and_overseas_counts(self):
        self.assertEqual(self.stats["on_map"], 1)
        self.assertEqual(self.stats["overseas"], 1)
        self.assertIn('data-lat="37.28"', self.index)
        self.assertIn("<p>미국</p><strong>1개</strong>", self.index)

    def test_sitemap_and_canonical(self):
        sitemap = (self.out / "sitemap.xml").read_text(encoding="utf-8")
        self.assertEqual(sitemap.count("<url>"), 5)
        self.assertIn('<link rel="canonical" href="https://jobs.example/index.html">', self.index)

    def test_kakao_key_reaches_page_config(self):
        self.assertIn('window.SITE = {"kakaoKey": "KEY"', self.index)

    def test_rebuild_removes_expired_pages(self):
        conn = cj.init_db(self.db)
        conn.execute("UPDATE jobs SET deadline = '2026-10-28' WHERE title = '아주대 강사 모집'")
        conn.commit()
        conn.close()
        stats = bs.build(self.db, self.out, self.config, TODAY, BUILT_AT)
        self.assertEqual(stats["jobs"], 2)
        self.assertNotIn("아주대 강사 모집", (self.out / "index.html").read_text(encoding="utf-8"))


class BadgeTests(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(bs.deadline_badge("2026-10-29", TODAY), ("오늘 마감", "urgent"))
        self.assertEqual(bs.deadline_badge("2026-11-01", TODAY), ("마감 D-3", "urgent"))
        self.assertEqual(bs.deadline_badge("2026-12-01", TODAY), ("D-33", ""))
        self.assertEqual(bs.deadline_badge("rolling", TODAY), ("상시 모집", "rolling"))
        self.assertEqual(bs.deadline_badge(None, TODAY), ("마감일 원문 확인", ""))

    def test_display_title_drops_board_clutter(self):
        self.assertEqual(bs.display_title("N 미국 Emory University 한국어 교수"), "미국 Emory University 한국어 교수")
        self.assertEqual(bs.display_title("(제2026-02-011호) 2026년 강북구가족센터 강사"), "2026년 강북구가족센터 강사")
        self.assertEqual(bs.display_title("Nagoya University 강사"), "Nagoya University 강사")
        self.assertEqual(
            bs.display_title("성신여자대학교 국제교육원 한국어강사 모집 공고 접수중 2026.07.22~2026.07.29"),
            "성신여자대학교 국제교육원 한국어강사 모집 공고",
        )

    def test_script_json_cannot_close_tag(self):
        self.assertNotIn("</script>", bs.json_for_script({"x": "</script><b>"}))


if __name__ == "__main__":
    unittest.main()
