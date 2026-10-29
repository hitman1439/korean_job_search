"""Regression tests for the collector's parsers and DB rules.

Run from the project root:  python -m unittest discover -s tests
Text fixtures are trimmed from real collected pages.
"""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import collect_jobs as cj  # noqa: E402
import extract_fields as ef  # noqa: E402

TODAY = dt.date(2026, 10, 29)

# 해커스 상세 페이지: 본문에 근무지가 없고, 푸터에 사이트 운영사 주소(서울 서초구)가 있다.
HACKERS_LIKE = (
    "한국어교원 - 해커스원격평생교육원 본문내용 바로가기 개인정보취급방침 보기 "
    + "공고 본문 " * 80
    + "[아주대학교 국제교육센터] 한국어 강사·객원강사 채용 모집 마감일 2026/11/06 "
    + "교육원 소개 이용약관 개인정보처리방침 정보공시 TEL : 1544-7558 "
    "서울시 서초구 서초동 1317-31 세계빌딩 7층 | 사업자등록번호 : 214-88-88452"
)

KLEOCEAN_US = (
    "미국 Emory University 한국어 교수 해외 채용 공고 작성자 운영자 작성일 2026-10-08 06:29 "
    "회사명 : Emory University 근무지역 : 미국 고용형태 : 풀타임 "
    "Candidates must be authorized to work in the USA by the start of appointment. "
    "Review of applications will start on November 15 and continue until the position is filled."
)


class DeadlineTests(unittest.TestCase):
    def test_korean_label(self):
        self.assertEqual(cj.extract_deadline("접수기간: 2026. 10. 1. ~ 2026. 11. 6.", TODAY), "2026-11-06")

    def test_employment_period_is_not_deadline(self):
        text = "근무기간 2026.9.1. ~ 2027.8.31. 문의 바랍니다"
        self.assertIsNone(cj.extract_deadline(text, TODAY))

    def test_bare_tilde_needs_application_context(self):
        self.assertIsNone(cj.extract_deadline("행사 일정 안내 ~ 2026.12.01", TODAY))
        self.assertEqual(cj.extract_deadline("서류 제출: 2026.11.01 ~ 2026.11.20", TODAY), "2026-11-20")

    def test_english_month_day_year(self):
        text = "Review of applications will begin on December 1, 2026."
        self.assertEqual(cj.extract_deadline(text, TODAY), "2026-12-01")

    def test_english_without_year_uses_next_occurrence(self):
        self.assertEqual(cj.extract_deadline(KLEOCEAN_US, TODAY), "2026-11-15")
        self.assertEqual(cj.extract_deadline("Application deadline: January 10", TODAY), "2027-01-10")

    def test_english_day_month_year(self):
        self.assertEqual(cj.extract_deadline("Closing date: 15 November 2026", TODAY), "2026-11-15")

    def test_english_weekday_prefix(self):
        text = "Next review date: Monday, Nov 2, 2026 at 11:59pm (Pacific Time)"
        self.assertEqual(cj.extract_deadline(text, TODAY), "2026-11-02")

    def test_japanese(self):
        self.assertEqual(cj.extract_deadline("応募締切：2026年11月30日（必着）", TODAY), "2026-11-30")

    def test_rolling(self):
        self.assertEqual(cj.extract_deadline("마감일 : 채용까지", TODAY), "rolling")
        self.assertEqual(cj.extract_deadline("The position is open until filled.", TODAY), "rolling")
        # "상시" on its own (상시 근무) is not a rolling deadline.
        self.assertIsNone(cj.extract_deadline("주 5일 상시 근무", TODAY))


class LocationTests(unittest.TestCase):
    def test_site_footer_address_is_ignored(self):
        self.assertIsNone(cj.extract_location(HACKERS_LIKE))

    def test_labeled_work_region(self):
        self.assertEqual(cj.extract_location(KLEOCEAN_US), "미국")
        self.assertEqual(cj.extract_location("근무지 : 경기도 수원시 영통구"), "경기")

    def test_gyeonggi_gwangju_city_is_not_gwangju_metro(self):
        self.assertEqual(cj.extract_location("주소: 경기도 광주시 오포읍"), "경기")
        self.assertIsNone(cj.short_region("광주시"))
        self.assertEqual(cj.short_region("광주광역시 북구"), "광주")

    def test_bare_words_that_are_not_regions(self):
        self.assertIsNone(cj.extract_location("2026년 세종학당 국외 파견 한국어 교원 선발"))
        self.assertIsNone(cj.extract_location("(2) 해외여행에 결격사유가 없는 자"))
        self.assertIsNone(cj.extract_location("서울대학교 언어교육원 강사 모집"))
        self.assertEqual(cj.extract_location("근무: 부산 소재 한국어학원"), "부산")

    def test_region_from_geocoded_address(self):
        self.assertEqual(cj.short_region("경기 수원시 영통구 월드컵로 206"), "경기")
        self.assertEqual(cj.short_region("전북특별자치도 전주시 완산구"), "전북")


class InstitutionTests(unittest.TestCase):
    def test_bracketed_title_fallback(self):
        self.assertEqual(cj.extract_bracketed_institution("[마이코리안] 한국어 강사 채용"), "마이코리안")

    def test_board_tag_is_not_institution(self):
        self.assertIsNone(cj.extract_bracketed_institution("[홍보] 세종학당재단 국외 파견 교원 선발"))
        self.assertEqual(cj.extract_bracketed_institution("[공고] [숭실대학교] 강사 채용"), "숭실대학교")

    def test_run_on_institution_trimmed(self):
        self.assertEqual(cj.tidy_institution("가을 · 겨울학기 이화여자대학교 언어교육원"), "이화여자대학교 언어교육원")
        self.assertEqual(
            cj.tidy_institution("연세대학교 한국어학당 한국어강사 모집 공고 연세대학교 언어연구교육원 한국어학당"),
            "연세대학교 한국어학당",
        )
        self.assertEqual(cj.clean_extracted_field("2026년도 여름학기 서강대학교", None), "여름학기 서강대학교")

    def test_notice_number_prefix_stripped(self):
        cleaned = cj.clean_extracted_field("(제2026-02-011호) 2026년 강북구가족센터", None)
        self.assertEqual(cleaned, "강북구가족센터")

    def test_institution_core_groups_reposts(self):
        a = cj.institution_core("아주대학교 국제교육센터", "")
        b = cj.institution_core("아주대학교", "국제교육센터 한국어 강사 초빙")
        c = cj.institution_core(None, "[아주대학교 국제교육센터] 한국어 강사 채용")
        self.assertEqual(a, b)
        self.assertEqual(b, c)


def make_job(**overrides):
    job = {
        "title": "한국어 강사 채용",
        "institution_name": "아주대학교",
        "source_name": "test",
        "source_url": "https://example.org/list",
        "original_url": "https://example.org/1",
        "location_text": "경기",
        "deadline": "2026-11-06",
        "posted_at": None,
        "collected_at": "2026-10-20T00:00:00+00:00",
        "description": "본문",
        "raw_text": "본문",
        "confidence_score": 80,
        "status": "needs_review",
    }
    job.update(overrides)
    job["content_hash"] = cj.make_content_hash(job["title"], job["institution_name"], job["deadline"], job["original_url"])
    job["duplicate_group_id"] = job["content_hash"][:16]
    return job


KTEACHER_ROW = """<table class="desktopShow"><tbody><tr> <td>1</td> <td> 국내 </td>
<td> <a title="숭실대학교 한국어교육원 한국어강사 채용 공고" href="/certif/jobsearch/35051" >숭실대학교 한국어교육원 한국어강사 채용 공고</a> </td>
<td>숭실대학교 한국어교육원</td> <td> <span class="formattedDate"> 20261027 </span> </td>
<td> <span class="replace-formatted-date"> 2026-11-09 </span> </td> </tr></tbody></table>"""


GOE_LISTING = """<div class="recruit_list"><ul> <li> <a href="javascript:goView('64257');"> <div class="cont_txt">
<div class="cont_top"> <span>성포초등학교</span> <span>031-487-4313</span> <span>등록일 : 2026/10/29</span> </div>
<p class="cont_tit"> <span class="krds-badge bg4">마감임박 </span> 2026 한국어학급 강사 채용 공고 </p> </div></a> </li></ul></div>"""


class SourceParserTests(unittest.TestCase):
    def test_jinhakpro_sitemap_keeps_korean_teaching_calls_only(self):
        conn = cj.init_db(Path(":memory:"))
        pages = {
            "https://www.jinhakpro.com/sitemap.xml":
                "<url><loc>https://www.jinhakpro.com/recruit/101</loc></url><url><loc>https://www.jinhakpro.com/recruit/102</loc></url>",
            "https://www.jinhakpro.com/recruit/102":
                "<title>2026 겨울학기 한국어강사 채용 - 가천대학교 | 진학프로</title><p>접수 마감일 : 2026-11-08</p>",
            "https://www.jinhakpro.com/recruit/101":
                "<title>2026 행정직원 채용 - 가천대학교 | 진학프로</title><p>한국어학당 강사 모집(사이드바)</p><p>마감일 : 2026-11-08</p>",
        }
        opened = []
        original = cj.fetch_url

        def fake_fetch(url, timeout=20):
            opened.append(url)
            return pages[url]

        cj.fetch_url = fake_fetch
        try:
            source = cj.DiscoverySource("진학프로", "https://www.jinhakpro.com/sitemap.xml", 85, "jinhakpro_sitemap", pages=10)
            items = cj.discover_jinhakpro_sitemap(conn, source, ["한국어"], [], TODAY)
            again = cj.discover_jinhakpro_sitemap(conn, source, ["한국어"], [], TODAY)
        finally:
            cj.fetch_url = original
        self.assertEqual([i.institution_hint for i in items], ["가천대학교"])
        self.assertEqual(items[0].deadline_hint, "2026-11-08")
        # The staff call is remembered and not opened on the next run.
        self.assertEqual(opened.count("https://www.jinhakpro.com/recruit/101"), 1)
        conn.close()

    def test_goe_recruit_rows(self):
        responses = iter(["<html>search page</html>", GOE_LISTING])
        original = cj.open_with_opener
        cj.open_with_opener = lambda opener, request, timeout: next(responses)
        try:
            source = cj.DiscoverySource("경기도교육청", "https://www.goe.go.kr/recruit/ad/func/pb/hnfpPbancList.do?mi=10502",
                                        85, "goe_recruit", terms=("한국어",))
            items = cj.discover_goe_recruit(source)
        finally:
            cj.open_with_opener = original
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title_hint, "2026 한국어학급 강사 채용 공고")
        self.assertEqual(items[0].institution_hint, "성포초등학교")
        self.assertTrue(items[0].url.endswith("pbancSn=64257"))

    def test_kteacher_rows_on_moved_board(self):
        rows = cj.parse_kteacher_rows(KTEACHER_ROW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["path"], "/certif/jobsearch/35051")
        self.assertEqual(rows[0]["deadline"], "2026-11-09")
        self.assertEqual(rows[0]["institution"], "숭실대학교 한국어교육원")

    def test_same_path_post_links_are_kept(self):
        board = (
            '<a href="/board/?pageid=2">2</a>'
            '<a href="/board/?mod=document&#038;uid=623">성신여대 한국어강사 모집 공고</a>'
            '<a href="/board/?category=한국어강사">한국어 강사 모집 분류</a>'
        )
        source = cj.DiscoverySource("test", "https://example.org/board/", 70, "generic_links")
        original = cj.fetch_url
        cj.fetch_url = lambda url, timeout=20: board
        try:
            items = cj.discover_generic_links(source, ["한국어"], ["모집"])
        finally:
            cj.fetch_url = original
        self.assertEqual([i.url for i in items], ["https://example.org/board/?mod=document&uid=623"])

    def test_posted_at_inferred_from_dates_and_title_year(self):
        old = "2024학년도 겨울학기 한국어 교사 모집 공고 접수 2024.10.01 ~ 2024.10.15 문의"
        self.assertEqual(cj.infer_posted_at(old, "2024학년도 겨울학기 한국어 교사 모집 공고", TODAY), "2024-10-15")
        self.assertEqual(cj.infer_posted_at("내용은 첨부 참조", "2017년 가을학기 한국어 강사 모집", TODAY), "2017-12-31")
        # A date still ahead means the notice is running: no guess.
        self.assertIsNone(cj.infer_posted_at("근무 2026.12.01 ~ 2027.02.28", "겨울학기 강사 모집", TODAY))
        self.assertEqual(cj.infer_posted_at("작성일 2026-10-20 본문", "강사 모집", TODAY), "2026-10-20")

    def test_started_term_means_closed(self):
        self.assertEqual(cj.infer_posted_at("본문", "2026학년도 여름학기 한국어 강사 초빙 공고", TODAY), "2026-05-31")
        self.assertEqual(cj.infer_posted_at("본문", "2026년도 가을학기 한국어 강사 모집", TODAY), "2026-08-31")
        # Winter term starts in December: an October call is still open.
        self.assertIsNone(cj.infer_posted_at("본문", "2026년 겨울학기 한국어 강사 모집공고", TODAY))

    def test_generic_links_need_a_teaching_role(self):
        board = (
            '<a href="/b/?uid=1">2025년도 한국어 정규과정 모집요강</a>'
            '<a href="/b/?uid=2">「계약직 직원」채용 공고 (한국어 문화교육원)</a>'
            '<a href="/b/?uid=3">한국어 문화교육원 한국어 교사 모집 공고</a>'
        )
        source = cj.DiscoverySource("test", "https://example.org/b/", 70, "generic_links")
        original = cj.fetch_url
        cj.fetch_url = lambda url, timeout=20: board
        try:
            items = cj.discover_generic_links(source, ["한국어"], ["모집", "채용"])
        finally:
            cj.fetch_url = original
        self.assertEqual([i.url for i in items], ["https://example.org/b/?uid=3"])

    def test_notice_files_are_found_by_their_link_text(self):
        page = cj.parse_html(
            '<a href="/certif/file/download?fileNo=11032&bigCate=board">1. 숭실대학교_채용공고문.pdf</a>'
            '<a href="/certif/file/download?fileNo=11033">2. 지원서 양식_2026.hwp </a>'
            '<a href="/certif/jobsearch/list">목록</a><a href="javascript:fnDown(3)">3. 동의서.hwp</a>'
        )
        files = cj.extract_attachments(page.links, "https://klp.korean.go.kr/certif/jobsearch/35051")
        self.assertEqual(files, [
            ("숭실대학교_채용공고문.pdf", "https://klp.korean.go.kr/certif/file/download?fileNo=11032&bigCate=board"),
            ("지원서 양식_2026.hwp", "https://klp.korean.go.kr/certif/file/download?fileNo=11033"),
        ])

    def test_rate_limited_host_is_skipped_for_the_run(self):
        import urllib.error
        calls = []
        original_once, original_sleep = cj.fetch_url_once, cj.time.sleep

        def always_429(url, timeout):
            calls.append(url)
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)

        cj.fetch_url_once, cj.time.sleep = always_429, (lambda s: None)
        try:
            with self.assertRaises(cj.HostRateLimited):
                cj.fetch_url("https://limited.example/1")
            tried = len(calls)
            with self.assertRaises(cj.HostRateLimited):
                cj.fetch_url("https://limited.example/2")
        finally:
            cj.fetch_url_once, cj.time.sleep = original_once, original_sleep
            cj._BLOCKED_HOSTS.discard("limited.example")
        # The second URL is refused without another request.
        self.assertEqual(len(calls), tried)

    def test_a_hung_request_is_abandoned(self):
        import time as _time
        started = _time.monotonic()
        with self.assertRaises(TimeoutError):
            cj.with_deadline(_time.sleep, (5,), 0.2)
        self.assertLess(_time.monotonic() - started, 2)
        self.assertEqual(cj.with_deadline(lambda a, b: a + b, (1, 2), 1), 3)

    def test_attachment_links_are_not_postings(self):
        self.assertTrue(cj.ATTACHMENT_LINK.search("https://www.yu.ac.kr/main/intro/yu-news.do?mode=fileDownload&articleNo=1"))
        self.assertTrue(cj.ATTACHMENT_LINK.search("https://x.ac.kr/files/한국어강사 모집 공고.hwp"))
        self.assertFalse(cj.ATTACHMENT_LINK.search("https://x.ac.kr/bbs/kr/1/2/artclView.do"))

    def test_closed_posts_are_not_reopened(self):
        conn = cj.init_db(Path(":memory:"))
        fetched = []
        original = cj.fetch_url

        def fake_fetch(url, timeout=20):
            fetched.append(url)
            return "<h1>한국어 강사 모집</h1> 접수기간: 2026.09.01 ~ 2026.09.10"

        cj.fetch_url = fake_fetch
        try:
            source = cj.Source("board", "https://x.ac.kr/post/1", 80, "discovered_url")
            for _ in range(2):
                cj.collect_seed_urls(conn, 1, [source], ["한국어"], ["모집"], [], TODAY, True)
        finally:
            cj.fetch_url = original
        self.assertEqual(fetched, ["https://x.ac.kr/post/1"])
        conn.close()


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.conn = cj.init_db(Path(":memory:"))

    def tearDown(self):
        self.conn.close()

    def test_attachments_are_mirrored_once(self):
        import json
        import tempfile
        from unittest import mock

        cj.save_job(self.conn, make_job())
        files = json.dumps([
            {"name": "공고문.pdf", "url": "https://board.example/f?1"},
            {"name": "양식.hwp", "url": "https://board.example/f?2"},
        ], ensure_ascii=False)
        self.conn.execute("UPDATE jobs SET attachments = ?", (files,))
        answers = {"https://board.example/f?1": b"%PDF", "https://board.example/f?2": ValueError("login wall")}

        def fake_fetch(url):
            answer = answers[url]
            if isinstance(answer, Exception):
                raise answer
            return answer

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(cj, "fetch_file", side_effect=fake_fetch) as fetch:
            stats = cj.mirror_attachments(self.conn, Path(tmp))
            self.assertEqual(stats, {"mirrored": 1, "failed": 1})
            stored = json.loads(self.conn.execute("SELECT attachments FROM jobs").fetchone()[0])
            self.assertEqual(stored[0]["file"], "1/1.pdf")
            self.assertEqual((Path(tmp) / "1" / "1.pdf").read_bytes(), b"%PDF")
            self.assertNotIn("file", stored[1])
            fetch.reset_mock()
            cj.mirror_attachments(self.conn, Path(tmp))
            self.assertEqual([c.args[0] for c in fetch.call_args_list], ["https://board.example/f?2"])

    def test_recollection_keeps_review(self):
        cj.save_job(self.conn, make_job())
        self.conn.execute("UPDATE jobs SET status = 'approved', review_note = 'ok'")
        cj.save_job(self.conn, make_job(original_url="https://example.org/1?page=2"))
        status, note, first_seen = self.conn.execute(
            "SELECT status, review_note, first_seen_at FROM jobs"
        ).fetchone()
        self.assertEqual((status, note), ("approved", "ok"))
        self.assertEqual(first_seen, "2026-10-20T00:00:00+00:00")

    def test_cross_source_duplicates_marked_not_deleted(self):
        cj.save_job(self.conn, make_job(confidence_score=60))
        cj.save_job(
            self.conn,
            make_job(
                title="[아주대학교 국제교육센터] 한국어 강사 초빙",
                institution_name="아주대학교 국제교육센터",
                original_url="https://other.example/9",
                source_name="other board",
                confidence_score=90,
            ),
        )
        self.assertEqual(cj.assign_duplicate_groups(self.conn), 1)
        rows = self.conn.execute("SELECT confidence_score, is_canonical FROM jobs ORDER BY confidence_score").fetchall()
        self.assertEqual(rows, [(60, 0), (90, 1)])

    def test_undated_repost_joins_dated_original(self):
        cj.save_job(self.conn, make_job(title="숭실대학교 한국어교육원 한국어강사 채용 공고", institution_name="숭실대학교 한국어교육원",
                                        deadline="2026-11-09", confidence_score=88))
        cj.save_job(self.conn, make_job(title="숭실대학교 한국어교육원 한국어강사 채용 공고", institution_name=None,
                                        deadline=None, original_url="https://repost.example/1", confidence_score=95))
        cj.save_job(self.conn, make_job(title="New 일본 ハングルネット 한국어강사 해외 채용 공고", deadline=None,
                                        original_url="https://k.example/a"))
        cj.save_job(self.conn, make_job(title="일본 ハングルネット 한국어강사 해외 채용 공고", deadline=None,
                                        original_url="https://k.example/b"))
        self.assertEqual(cj.assign_duplicate_groups(self.conn), 2)
        # The dated original wins over the more trusted but undated repost.
        canonical = self.conn.execute(
            "SELECT deadline FROM jobs WHERE is_canonical = 1 AND title LIKE '숭실%'"
        ).fetchall()
        self.assertEqual(canonical, [("2026-11-09",)])

    def apply_rows(self):
        return dict(self.conn.execute("SELECT title, apply_url || ' ' || apply_url_source FROM jobs").fetchall())

    def test_apply_link_prefers_the_institution(self):
        # A notice on the aggregator and the same notice on the university's board.
        cj.save_job(self.conn, make_job(title="숭실대 한국어강사 채용", deadline="2026-11-09",
                                        original_url="https://klp.korean.go.kr/certif/jobsearch/35051", source_name="국립국어원"))
        cj.save_job(self.conn, make_job(title="숭실대 한국어강사 채용 공고", deadline="2026-11-09",
                                        original_url="https://ssu.ac.kr/notice/1234", source_name="숭실대",
                                        confidence_score=60))
        # An aggregator copy whose body links the university post.
        cj.save_job(self.conn, make_job(title="남서울대 강사 채용", institution_name="남서울대학교", deadline="2026-11-06",
                                        original_url="https://www.iakle.com/subList/1?nttSeq=9",
                                        raw_text="자세한 내용 https://nsu.ac.kr/bbs/view/77 참조, 홈페이지 https://nsu.ac.kr/"))
        # An aggregator copy with nothing better.
        cj.save_job(self.conn, make_job(title="한글넷 강사 채용", institution_name="한글넷", deadline="2026-11-30",
                                        original_url="https://klp.korean.go.kr/certif/jobsearch/35059",
                                        raw_text="https://kteacher.korean.go.kr/org 참조"))
        # A post on the institution's own board.
        cj.save_job(self.conn, make_job(title="동국대 강사 초빙", institution_name="동국대학교", deadline="2026-11-15",
                                        original_url="https://interlang.dongguk.edu/bbs/board.php?wr_id=763"))
        cj.assign_duplicate_groups(self.conn)
        cj.resolve_apply_urls(self.conn)
        rows = self.apply_rows()
        canonical = [t for (t,) in self.conn.execute("SELECT title FROM jobs WHERE is_canonical = 1 AND title LIKE '숭실%'")][0]
        self.assertEqual(rows[canonical], "https://ssu.ac.kr/notice/1234 " + ("original" if "공고" in canonical else "group"))
        self.assertEqual(rows["남서울대 강사 채용"], "https://nsu.ac.kr/bbs/view/77 body")
        self.assertEqual(rows["한글넷 강사 채용"], "https://klp.korean.go.kr/certif/jobsearch/35059 aggregator")
        self.assertEqual(rows["동국대 강사 초빙"], "https://interlang.dongguk.edu/bbs/board.php?wr_id=763 original")

    def test_search_runs_once_per_posting(self):
        cj.save_job(self.conn, make_job(title="[공고] 서강대학교 한국어교육원 2026 겨울학기 시간강사 선발 공고",
                                        institution_name="서강대학교 한국어교육원", deadline=None,
                                        original_url="https://www.iakle.com/subList/1?nttSeq=21"))
        cj.assign_duplicate_groups(self.conn)
        calls = []
        original = cj.naver_search

        def fake_search(query, cid, secret):
            calls.append(query)
            return [
                {"link": "https://klp.korean.go.kr/x", "title": "서강대학교 한국어교육원 겨울학기 시간강사 선발"},
                {"link": "https://korean.sogang.ac.kr/bbs/view/5", "title": "<b>서강대학교</b> 한국어교육원 2026 겨울학기 시간강사 선발 공고"},
            ]

        cj.naver_search = fake_search
        try:
            cj.resolve_apply_urls(self.conn, ("id", "secret"))
            cj.resolve_apply_urls(self.conn, ("id", "secret"))
        finally:
            cj.naver_search = original
        self.assertEqual(len(calls), 1)
        self.assertEqual(list(self.apply_rows().values()), ["https://korean.sogang.ac.kr/bbs/view/5 search"])

    def test_two_positions_on_one_board_stay_apart(self):
        cj.save_job(self.conn, make_job(title="세종대학교 세종어학원 한국어과정 시간강사 초빙 공고", institution_name="세종대학교 세종어학원",
                                        deadline="2026-11-12", source_name="국립국어원"))
        cj.save_job(self.conn, make_job(title="세종대학교 세종어학원 한국어과정 강의전담강사 초빙 공고", institution_name="세종대학교 세종어학원",
                                        deadline="2026-11-12", source_name="국립국어원", original_url="https://example.org/2"))
        self.assertEqual(cj.assign_duplicate_groups(self.conn), 0)

    def test_title_key_drops_board_markers(self):
        self.assertEqual(cj.title_key("남서울대학교 겨울학기 한국어 강사 채용 공고-2"), cj.title_key("남서울대학교 겨울학기 한국어 강사 채용 공고"))
        self.assertEqual(cj.title_key("N 미국 Emory University 한국어 교수"), cj.title_key("미국 Emory University 한국어 교수"))

    def test_old_rolling_posting_expires(self):
        self.assertFalse(cj.is_live_job("rolling", "2025-12-23", None, TODAY))
        self.assertTrue(cj.is_live_job("rolling", "2026-09-01", None, TODAY))

    def test_undated_jobs_survive_grace_period_then_go(self):
        cj.save_job(self.conn, make_job(deadline=None, collected_at="2026-10-01T00:00:00+00:00"))
        cj.save_job(
            self.conn,
            make_job(deadline=None, original_url="https://example.org/2", title="오래된 공고",
                     collected_at="2026-08-01T00:00:00+00:00"),
        )
        cj.save_job(self.conn, make_job(deadline="2026-10-01", original_url="https://example.org/3", title="마감"))
        self.assertEqual(cj.prune_inactive_jobs(self.conn, TODAY), 2)
        remaining = self.conn.execute("SELECT original_url FROM jobs").fetchall()
        self.assertEqual(remaining, [("https://example.org/1",)])

    def test_undated_grace_counts_from_posting_date(self):
        # Seen for the first time today, but posted in May: already stale.
        self.assertFalse(cj.is_live_job(None, "2026-05-01", "2026-10-29T00:00:00+00:00", TODAY))
        self.assertTrue(cj.is_live_job(None, "2026-10-10", None, TODAY))

    def test_retired_sources_purged(self):
        cj.save_job(self.conn, make_job(source_name="하이브레인넷 한국어 채용검색"))
        cj.save_job(self.conn, make_job(original_url="https://example.org/2", title="다른 공고"))
        self.assertEqual(cj.purge_retired_sources(self.conn, {"하이브레인넷 한국어 채용검색"}), 1)


class FieldRuleTests(unittest.TestCase):
    def test_domestic_posting(self):
        job = {
            "title": "화성시글로벌청소년센터 찾아가는 한국어 교육 강사 채용",
            "institution_name": "화성시글로벌청소년센터",
            "location_text": "경기",
            "deadline": "rolling",
            "raw_text": "자격: 한국어교원 자격증 3급 이상 소지자, 신입 가능. 강사료: 시간당 30,000원. 전형: 서류 및 모의수업",
        }
        fields = ef.extract_rules(job)
        self.assertEqual(fields["country"], "대한민국")
        self.assertEqual(fields["qualification"], "한국어교원 3급 이상")
        self.assertEqual(fields["newcomer_ok"], 1)
        self.assertEqual(fields["demo_lesson"], 1)
        self.assertEqual(fields["salary_text"], "시간당 30,000원")

    def test_overseas_posting(self):
        job = {
            "title": "미국 Emory University 한국어 교수 해외 채용 공고",
            "institution_name": "Emory University",
            "location_text": "미국",
            "deadline": "2026-11-15",
            "raw_text": KLEOCEAN_US + " A teaching demonstration is required. Visa sponsorship available.",
        }
        fields = ef.extract_rules(job)
        self.assertEqual(fields["country"], "미국")
        self.assertEqual(fields["is_overseas"], 1)
        self.assertEqual(fields["institution_type"], "overseas_university")
        self.assertEqual(fields["demo_lesson"], 1)
        self.assertEqual(fields["benefits"], "비자")

    def test_experience_required_means_not_newcomer(self):
        fields = ef.extract_rules({"title": "강사 채용", "raw_text": "한국어 강의 경력 1년 이상인 자"})
        self.assertEqual(fields["experience_required"], "경력 1년 이상")
        self.assertEqual(fields["newcomer_ok"], 0)

    def test_salary_is_only_the_amount(self):
        self.assertEqual(ef.detect_salary("강사료: 화, 목요일 배정 시 : 시간당 32,000 원"), "시간당 32,000 원")
        self.assertEqual(ef.detect_salary("시급 35,000원"), "시간당 35,000원")
        self.assertEqual(ef.detect_salary("연봉 3,600만원 이상"), "3,600만원")
        self.assertIsNone(ef.detect_salary("강의료는 내부 기준에 따름"))

    def test_apply_email_skips_the_boards_own_address(self):
        text = "문의 kteacher@korean.go.kr 접수: 이메일(ili3@sejong.ac.kr)로 제출."
        self.assertEqual(ef.detect_apply_email(text), "ili3@sejong.ac.kr")
        self.assertIsNone(ef.detect_apply_email("방문 접수만 받습니다."))

    def test_indonesia_is_not_india(self):
        self.assertEqual(ef.detect_country("인도네시아 대학 한국어 강사", None, ""), "인도네시아")


class LlmRequestTests(unittest.TestCase):
    """Checks what we send and how we read the reply, without calling the API."""

    def make_stub(self, stop_reason="end_turn", payload=None):
        from types import SimpleNamespace

        calls = []
        reply = payload or {
            "institution_type": "overseas_university", "country": "미국", "qualification": None,
            "experience_required": "강의 경력 2년 이상", "newcomer_ok": False, "demo_lesson": True,
            "salary_text": None, "benefits": "비자", "summary": "에모리 대학교가 한국어 교수를 뽑습니다.",
        }

        def create(**kwargs):
            calls.append(kwargs)
            block = SimpleNamespace(type="text", text=__import__("json").dumps(reply, ensure_ascii=False))
            return SimpleNamespace(stop_reason=stop_reason, content=[block])

        client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
        return client, calls

    def test_request_and_parse(self):
        client, calls = self.make_stub()
        fields = ef.extract_llm(client, {"job_id": 1, "title": "Emory"}, "posting text")
        request = calls[0]
        self.assertEqual(request["model"], "claude-opus-5-5")
        self.assertEqual(request["extra_body"]["fallbacks"], "default")
        self.assertEqual(request["extra_body"]["output_config"]["format"]["schema"], ef.LLM_SCHEMA)
        self.assertEqual((fields["newcomer_ok"], fields["demo_lesson"], fields["is_overseas"]), (0, 1, 1))

    def test_refusal_returns_none(self):
        client, _ = self.make_stub(stop_reason="refusal")
        self.assertIsNone(ef.extract_llm(client, {"job_id": 1}, "text"))

    def test_missing_credentials_fall_back_to_rules(self):
        conn = cj.init_db(Path(":memory:"))
        cj.save_job(conn, make_job())
        cj.save_job(conn, make_job(original_url="https://example.org/2", title="다른 공고"))

        def unavailable(job, text):
            raise ef.LlmUnavailable("no key")

        original = ef.make_extractor
        ef.make_extractor = lambda backend: unavailable
        try:
            stats = cj.fill_job_fields(conn, "claude-code", 50)
        finally:
            ef.make_extractor = original
        self.assertEqual(stats, {"rules": 2, "llm": 0, "llm_failed": 0})
        conn.close()

    def run_claude_code(self, returncode, reply):
        """extract_claude_code against a fake `claude -p` run."""
        import json
        import subprocess
        from types import SimpleNamespace

        seen = {}

        def fake_run(command, **kwargs):
            seen["command"], seen["input"] = command, kwargs["input"].decode("utf-8")
            return SimpleNamespace(returncode=returncode, stdout=json.dumps(reply).encode("utf-8"), stderr=b"")

        original = subprocess.run
        subprocess.run = fake_run
        try:
            return ef.extract_claude_code("claude", {"job_id": 7, "title": "한성대 강사 모집"}, "본문"), seen
        finally:
            subprocess.run = original

    def test_claude_code_success(self):
        payload = {
            "institution_type": "university", "country": "대한민국", "qualification": "한국어교원 2급 이상",
            "experience_required": None, "newcomer_ok": True, "demo_lesson": None,
            "salary_text": "시간당 35,000원", "benefits": None, "summary": "한성대가 강사를 뽑습니다.",
        }
        fields, seen = self.run_claude_code(0, {"is_error": False, "structured_output": payload})
        self.assertEqual((fields["newcomer_ok"], fields["is_overseas"]), (1, 0))
        self.assertIn("--json-schema", seen["command"])
        self.assertEqual(seen["command"][seen["command"].index("--tools") + 1], "")
        self.assertIn("한성대 강사 모집", seen["input"])

    def test_claude_code_not_logged_in_stops_run(self):
        with self.assertRaises(ef.LlmUnavailable):
            self.run_claude_code(1, {"is_error": True, "result": "Not logged in · Please run /login"})

    def test_claude_code_other_failure_skips_posting(self):
        fields, _ = self.run_claude_code(1, {"is_error": True, "result": "unexpected error"})
        self.assertIsNone(fields)

    def test_schema_requires_every_property(self):
        self.assertEqual(set(ef.LLM_SCHEMA["required"]), set(ef.LLM_SCHEMA["properties"]))


if __name__ == "__main__":
    unittest.main()
