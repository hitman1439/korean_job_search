"""Tests for serve.py: the save counter, 근무 후기, and the admin-only /test."""

from __future__ import annotations

import base64
import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import review_items  # noqa: E402
import serve  # noqa: E402

CLIENT = "0123456789abcdef0123456789abcdef"


class SaveCountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = serve.open_stats(Path(self.tmp.name) / "stats.sqlite3")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def saved(self, job_id):
        return self.conn.execute("SELECT SUM(saved), COUNT(*) FROM saves WHERE job_id = ?", (job_id,)).fetchone()

    def test_save_unsave_keeps_one_row(self):
        serve.record_save(self.conn, CLIENT, 7, True)
        serve.record_save(self.conn, CLIENT, 7, True)
        self.assertEqual(self.saved(7), (1, 1))
        serve.record_save(self.conn, CLIENT, 7, False)
        self.assertEqual(self.saved(7), (0, 1))

    def test_unsave_without_save_stores_nothing(self):
        serve.record_save(self.conn, CLIENT, 8, False)
        self.assertEqual(self.saved(8), (None, 0))

    def test_one_browser_is_capped(self):
        for job_id in range(serve.MAX_JOBS_PER_CLIENT):
            self.assertTrue(serve.record_save(self.conn, CLIENT, job_id, True))
        self.assertFalse(serve.record_save(self.conn, CLIENT, 99999, True))

    def test_parse_rejects_bad_input(self):
        self.assertEqual(serve.parse_save(b'{"job": "12", "client": "%s", "on": true}' % CLIENT.encode()), (CLIENT, 12, True))
        for body in (b"nope", b"[]", b'{"job": "1; drop", "client": "%s", "on": true}' % CLIENT.encode(),
                     b'{"job": "1", "client": "short", "on": true}',
                     b'{"job": "1", "client": "%s", "on": "yes"}' % CLIENT.encode()):
            self.assertIsNone(serve.parse_save(body), body)


class ReviewTests(unittest.TestCase):
    GOOD = {"org": " 경희대학교  국제캠퍼스 ", "items": {"pay_care": 5, "grow_learn": 4},
            "facts": {"class_size": "11~15명"}, "comment": " 좋아요 ", "pledge": True}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = serve.open_reviews(Path(self.tmp.name) / "reviews.sqlite3")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_clean_review_keeps_a_valid_review(self):
        review = review_items.clean_review(self.GOOD)
        self.assertEqual(review["org"], "경희대학교 국제캠퍼스")
        self.assertEqual(review["comment"], "좋아요")
        self.assertEqual(review["items"], {"pay_care": 5, "grow_learn": 4})

    def test_any_single_answer_is_a_review(self):
        for answer in ({"items": {"stab_hours": 3}}, {"facts": {"weekly_hours": "10~14시간"}}, {"comment": "한마디"}):
            self.assertIsNotNone(review_items.clean_review({"org": "A대학", "pledge": True, **answer}), answer)
        self.assertIsNone(review_items.clean_review({"org": "A대학", "pledge": True}))
        self.assertIsNone(review_items.clean_review({"org": "A대학", "pledge": True, "comment": "   "}))

    def test_no_review_without_the_pledge(self):
        for pledge in (None, False, "true", 1):
            data = {**self.GOOD, "pledge": pledge}
            self.assertIsNone(review_items.clean_review(data), pledge)

    def test_clean_review_rejects_bad_input(self):
        for change in ({"org": ""}, {"items": {"pay_care": 6}}, {"items": {"nope": 3}},
                       {"items": {"pay_care": "5"}}, {"items": {"pay_care": True}},
                       {"facts": {"class_size": "모름"}}, {"comment": "x" * 1001}, {"org": "x" * 81}):
            self.assertIsNone(review_items.clean_review({**self.GOOD, **change}), change)
        self.assertIsNone(review_items.clean_review([]))

    def test_record_review_stores_the_month_only(self):
        serve.record_review(self.conn, review_items.clean_review(self.GOOD))
        org, month = self.conn.execute("SELECT org, created_on FROM ratings").fetchone()
        self.assertEqual(org, "경희대학교 국제캠퍼스")
        self.assertRegex(month, r"^\d{4}-\d{2}$")

    def test_comment_shows_only_once_approved(self):
        rid = serve.record_review(self.conn, review_items.clean_review(self.GOOD))
        org = "경희대학교 국제캠퍼스"
        self.assertEqual(serve.org_reviews(self.conn, org)[0]["comment"], "")
        serve.set_review(self.conn, rid, "comment_status", "approved")
        self.assertEqual(serve.org_reviews(self.conn, org)[0]["comment"], "좋아요")
        serve.set_review(self.conn, rid, "comment_status", "rejected")
        self.assertEqual(serve.org_reviews(self.conn, org)[0]["comment"], "")

    def test_hidden_review_leaves_the_site(self):
        rid = serve.record_review(self.conn, review_items.clean_review(self.GOOD))
        serve.set_review(self.conn, rid, "status", "hidden")
        self.assertEqual(serve.org_reviews(self.conn, "경희대학교 국제캠퍼스"), [])
        self.assertEqual(serve.org_counts(self.conn), {})
        serve.set_review(self.conn, rid, "status", "shown")
        self.assertEqual(len(serve.org_reviews(self.conn, "경희대학교 국제캠퍼스")), 1)

    def test_story_asks_every_statement_and_fact_once(self):
        asked = [q[:2] for scene in review_items.STORY for q in scene["core"] + scene["more"]]
        self.assertEqual(len(asked), len(set(asked)))
        self.assertEqual({k for kind, k in asked if kind == "item"}, review_items.ITEM_KEYS)
        self.assertEqual({k for kind, k in asked if kind == "fact"}, set(review_items.FACT_OPTIONS))
        for scene in review_items.STORY:
            self.assertTrue(scene["core"], scene["key"])
            for q in scene["core"] + scene["more"]:
                if q[0] == "item":
                    # Five answers, one per score 1-5 in order: the page shows that number.
                    self.assertEqual(len(q[3]), 5, q[1])
        self.assertEqual(set(review_items.AREA_TYPES), {key for key, _, _ in review_items.AREAS})
        self.assertEqual(len(review_items.AREAS), 5)
        data = review_items.page_data()["story"][0]["core"][0]
        self.assertEqual([o["score"] for o in data["options"]], [1, 2, 3, 4, 5])

    def test_wording_stays_clear_of_legal_claims(self):
        # Statements and answers are the reviewer's feeling, never a charge
        # against the institution or one person, nor about students' origins.
        banned = ("보험", "퇴직금", "체불", "밀리", "쪼개", "원장", "주임", "관리자", "불법", "비자", "이탈", "국적", "목적")
        texts = [t for _, _, items in review_items.AREAS for _, t in items]
        for scene in review_items.STORY:
            texts.append(scene["scene"])
            for q in scene["core"] + scene["more"]:
                texts.append(q[2])
                if q[0] == "item":
                    texts.extend(q[3])
        for text in texts:
            for word in banned:
                self.assertNotIn(word, text, text)

    def test_summarize_adds_up_each_statement(self):
        reviews = [
            {"items": {"grow_learn": 4, "pay_care": 2, "retired_key": 1}, "facts": {"class_size": "11~15명"}, "comment": ""},
            {"items": {"grow_learn": 2}, "facts": {"class_size": "11~15명"}, "comment": "좋아요"},
        ]
        summary = review_items.summarize(reviews)
        self.assertEqual(summary["count"], 2)
        self.assertFalse(summary["public"])
        self.assertEqual(summary["items"], {"grow_learn": [6, 2], "pay_care": [2, 1]})
        self.assertEqual(summary["facts"], {"class_size": {"11~15명": 2}})
        # Text only: no date that could point at a writer.
        self.assertEqual(summary["comments"], ["좋아요"])
        self.assertTrue(review_items.summarize(reviews * 3)["public"])

    def test_log_line_has_no_address(self):
        handler = object.__new__(serve.Handler)
        handler.client_address = ("203.0.113.9", 51234)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            handler.log_message('"%s" %s %s', "POST /test/api/review HTTP/1.1", "204", "-")
        self.assertIn("/test/api/review", err.getvalue())
        self.assertNotIn("203.0.113.9", err.getvalue())


class AdminGateTests(unittest.TestCase):
    """/test is served from its own folder, only with the admin password."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        for name, text in (("site", "public"), ("site_test", "staging")):
            (base / name).mkdir()
            (base / name / "index.html").write_text(text, encoding="utf-8")
        handler = type("H", (serve.Handler,), {
            "test_dir": base / "site_test", "reviews_path": base / "reviews.sqlite3", "admin": ("admin", "pw"),
            "log_message": lambda *a: None,
        })
        cls.handler = handler
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(handler, directory=str(base / "site")))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def fetch(self, path, password=None, body=None):
        req = urllib.request.Request(self.base + path, data=body, method="POST" if body else "GET")
        if password:
            req.add_header("Authorization", "Basic " + base64.b64encode(f"admin:{password}".encode()).decode())
        if body:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, res.read().decode(), res.headers
        except urllib.error.HTTPError as err:
            return err.code, "", err.headers

    def test_public_site_needs_no_password(self):
        self.assertEqual(self.fetch("/index.html")[:2], (200, "public"))

    def test_test_needs_the_password(self):
        status, _, headers = self.fetch("/test/index.html")
        self.assertEqual(status, 401)
        self.assertIn("Basic", headers["WWW-Authenticate"])
        self.assertEqual(self.fetch("/test/index.html", "wrong")[0], 401)
        self.assertEqual(self.fetch("/%74est/index.html")[0], 401)

    def test_test_serves_the_staging_build_uncached(self):
        status, text, headers = self.fetch("/test/index.html", "pw")
        self.assertEqual((status, text), (200, "staging"))
        self.assertIn("no-store", headers["Cache-Control"])
        self.assertEqual(self.fetch("/test/../index.html", "pw")[:2], (200, "staging"))

    def test_review_post_needs_the_password(self):
        body = json.dumps({"org": "A대학", "items": {"grow_learn": 4}, "pledge": True}).encode()
        self.assertEqual(self.fetch("/test/api/review", body=body)[0], 401)
        self.assertEqual(self.fetch("/test/api/review", "pw", body)[0], 204)
        self.assertEqual(self.fetch("/test/api/review", "pw", b'{"org": "A"}')[0], 400)

    def test_ratings_api_returns_one_institutions_totals(self):
        body = json.dumps({"org": "B대학", "items": {"grow_learn": 5}, "comment": "좋아요", "pledge": True}).encode()
        self.fetch("/test/api/review", "pw", body)
        self.assertEqual(self.fetch("/test/api/ratings?org=B%EB%8C%80%ED%95%99")[0], 401)
        status, text, _ = self.fetch("/test/api/ratings?org=B%EB%8C%80%ED%95%99", "pw")
        data = json.loads(text)
        self.assertEqual((status, data["count"], data["items"]["grow_learn"]), (200, 1, [5, 1]))
        # Not public yet, and the 한마디 waits for approval.
        self.assertFalse(data["public"])
        self.assertEqual((data["comments"], data["pending"]), ([], 1))
        status, text, _ = self.fetch("/test/api/ratings", "pw")
        self.assertEqual(json.loads(text)["orgs"]["B대학"], 1)

    def test_no_password_set_means_no_test(self):
        self.handler.admin = None
        try:
            self.assertEqual(self.fetch("/test/index.html", "pw")[0], 404)
        finally:
            self.handler.admin = ("admin", "pw")


if __name__ == "__main__":
    unittest.main()
