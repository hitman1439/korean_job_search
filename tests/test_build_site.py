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

    def test_only_live_canonical_unrejected_domestic_jobs_publish(self):
        self.assertEqual(self.stats["jobs"], 2)
        self.assertNotIn("이미 마감", self.index)
        self.assertNotIn("반려된 공고", self.index)
        self.assertNotIn("중복 공고", self.index)
        self.assertEqual(len(list((self.out / "jobs").glob("*.html"))), 2)

    def test_public_build_hides_overseas(self):
        self.assertEqual(self.stats["overseas"], 0)
        self.assertNotIn("Smith College", self.index)
        self.assertNotIn('data-scope-btn="overseas"', self.index)
        self.assertNotIn('data-view="countries"', self.index)
        self.assertNotIn("noindex", self.index)

    def test_private_build_shows_overseas_and_stays_unindexed(self):
        private_out = Path(self.tmp.name) / "site_private"
        stats = bs.build(self.db, private_out, {**self.config, "private": True}, TODAY, BUILT_AT)
        index = (private_out / "index.html").read_text(encoding="utf-8")
        self.assertEqual(stats["overseas"], 1)
        self.assertIn("Smith College", index)
        self.assertIn('data-scope-btn="overseas"', index)
        self.assertIn('<meta name="robots" content="noindex, nofollow">', index)
        self.assertIn("비공개 미리보기", index)
        self.assertTrue((private_out / "resume.html").exists())
        self.assertFalse((private_out / "sitemap.xml").exists())
        self.assertEqual((private_out / "robots.txt").read_text(encoding="utf-8"), "User-agent: *\nDisallow: /\n")

    def test_untrusted_text_is_escaped(self):
        self.assertNotIn('<script>alert("x")</script>', self.index)
        self.assertIn("&lt;script&gt;", self.index)

    def test_non_http_links_are_never_linked(self):
        page = self.job_page("&lt;script&gt;")
        self.assertNotIn("javascript:alert", page)

    def test_job_page_has_valid_job_posting(self):
        page = self.job_page("아주대 강사 모집")
        raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1)
        data = json.loads(raw)
        self.assertEqual(data["@type"], "JobPosting")
        self.assertEqual(data["validThrough"], "2026-11-06T23:59:59+09:00")
        self.assertEqual(data["jobLocation"]["address"]["addressCountry"], "KR")
        self.assertIn("data-mini-map", page)

    def test_map_rows(self):
        self.assertEqual(self.stats["on_map"], 1)
        self.assertIn('data-lat="37.28"', self.index)

    def test_sitemap_and_canonical(self):
        sitemap = (self.out / "sitemap.xml").read_text(encoding="utf-8")
        self.assertEqual(sitemap.count("<url>"), 3)
        self.assertIn('<link rel="canonical" href="https://jobs.example/index.html">', self.index)

    def test_public_site_is_the_free_board_only(self):
        job = self.job_page("아주대 강사 모집")
        self.assertFalse((self.out / "resume.html").exists())
        self.assertFalse((self.out / "demo.html").exists())
        for page in (self.index, job):
            self.assertNotIn("resume.html", page)
            self.assertNotIn("demo.html", page)
        self.assertNotIn("모의수업이 있는 공고예요", job)
        # The free alert is offered on every job page instead.
        self.assertIn('href="../index.html#alert"', job)
        self.assertIn("새 공고 알림을 켜 두세요", job)

    def test_job_page_holds_everything_and_never_names_the_board(self):
        files = Path(self.tmp.name) / "files"
        (files / "1").mkdir(parents=True)
        (files / "1" / "1.pdf").write_bytes(b"%PDF-1.4")
        conn = cj.init_db(self.db)
        job_id = conn.execute("SELECT job_id FROM jobs WHERE title = '아주대 강사 모집'").fetchone()[0]
        conn.execute(
            """UPDATE jobs SET apply_email = 'ili3@sejong.ac.kr',
               attachments = '[{"name": "채용공고문.pdf", "url": "https://klp.korean.go.kr/certif/file/download?fileNo=1", "file": "1/1.pdf"},
                               {"name": "미러없음.hwp", "url": "https://klp.korean.go.kr/certif/file/download?fileNo=2"},
                               {"name": "악성.hwp", "url": "javascript:alert(1)", "file": "../../x.hwp"}]',
               apply_url = 'https://klp.korean.go.kr/certif/jobsearch/35051', apply_url_source = 'aggregator',
               original_url = 'https://klp.korean.go.kr/certif/jobsearch/35051',
               work_period = '2026.12.07 ~ 2027.02.18',
               body_text = '## 지원 자격
- 한국어교원 2급 이상
국립국어원 한국어교원 구인정보

## 접수 방법
이메일 ili3@sejong.ac.kr 또는 https://forms.example/apply 로 제출 (https://klp.korean.go.kr/certif/jobsearch/35051)'
               WHERE job_id = ?""",
            (job_id,),
        )
        conn.execute("UPDATE jobs SET apply_email = 'x\"><script>@bad' WHERE title LIKE '%script%'")
        conn.commit()
        conn.close()
        bs.build(self.db, self.out, {**self.config, "files_dir": str(files)}, TODAY, BUILT_AT)
        page = self.job_page("아주대 강사 모집")
        self.assertIn('href="mailto:ili3@sejong.ac.kr?subject=', page)
        self.assertIn('href="../files/1/1.pdf" download="채용공고문.pdf"', page)
        self.assertTrue((self.out / "files" / "1" / "1.pdf").exists())
        self.assertNotIn("미러없음.hwp", page)
        self.assertNotIn("악성.hwp", page)
        self.assertIn("<h3>지원 자격</h3>", page)
        self.assertIn("<li>한국어교원 2급 이상</li>", page)
        self.assertIn('href="https://forms.example/apply"', page)
        self.assertIn("<dt>근무 기간</dt><dd>2026.12.07 ~ 2027.02.18</dd>", page)
        for leak in ("korean.go.kr", "국립국어원", "원문", "출처"):
            self.assertNotIn(leak, page)
        self.assertNotIn("mailto:x", self.job_page("&lt;script&gt;"))

    def test_no_ad_boxes_until_asked(self):
        self.assertNotIn("ad-slot", self.index)
        out = Path(self.tmp.name) / "site_ads"
        bs.build(self.db, out, {**self.config, "ad_slots": True}, TODAY, BUILT_AT)
        self.assertIn('class="ad-slot display"', (out / "index.html").read_text(encoding="utf-8"))

    def test_services_appear_when_launched(self):
        out = Path(self.tmp.name) / "site_services"
        bs.build(self.db, out, {**self.config, "services": True}, TODAY, BUILT_AT)
        resume = (out / "resume.html").read_text(encoding="utf-8")
        self.assertIn('data-kind="resume"', resume)
        self.assertIn('aria-current="page">이력서·자소서 첨삭', resume)
        job = next(p.read_text(encoding="utf-8") for p in (out / "jobs").glob("*.html")
                   if "아주대 강사 모집" in p.read_text(encoding="utf-8"))
        self.assertIn('href="../resume.html"', job)
        self.assertIn("모의수업이 있는 공고예요", job)

    def test_kakao_key_reaches_page_config(self):
        self.assertIn('window.SITE = {"kakaoKey": "KEY"', self.index)

    def test_rebuild_removes_expired_pages(self):
        conn = cj.init_db(self.db)
        conn.execute("UPDATE jobs SET deadline = '2026-10-28' WHERE title = '아주대 강사 모집'")
        conn.commit()
        conn.close()
        stats = bs.build(self.db, self.out, self.config, TODAY, BUILT_AT)
        self.assertEqual(stats["jobs"], 1)
        self.assertNotIn("아주대 강사 모집", (self.out / "index.html").read_text(encoding="utf-8"))


class BadgeTests(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(bs.deadline_badge("2026-10-29", TODAY), ("오늘 마감", "urgent"))
        self.assertEqual(bs.deadline_badge("2026-11-01", TODAY), ("마감 D-3", "urgent"))
        self.assertEqual(bs.deadline_badge("2026-12-01", TODAY), ("D-33", ""))
        self.assertEqual(bs.deadline_badge("rolling", TODAY), ("상시 모집", "rolling"))
        self.assertEqual(bs.deadline_badge(None, TODAY), ("마감일 미정", ""))

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
