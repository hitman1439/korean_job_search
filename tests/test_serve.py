"""Tests for serve.py: the save counter, 기관 평가, and the admin-only /test."""

from __future__ import annotations

import base64
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
    GOOD = {"org": " 경희대학교 ", "overall": 4, "good": ["peers"], "bad": ["pay"], "areas": {"pay": 2},
            "items": {"pay_ontime": 5}, "closing": {"stay": 4}, "facts": {"insurance": "가입"}, "comment": " 좋아요 "}

    def test_clean_review_keeps_a_valid_review(self):
        review = review_items.clean_review(self.GOOD)
        self.assertEqual(review["org"], "경희대학교")
        self.assertEqual(review["comment"], "좋아요")
        self.assertEqual(review["areas"], {"pay": 2})

    def test_clean_review_needs_only_org_and_overall(self):
        self.assertIsNotNone(review_items.clean_review({"org": "A대학", "overall": 3}))

    def test_clean_review_rejects_bad_input(self):
        for change in ({"org": ""}, {"overall": 0}, {"overall": True}, {"areas": {"pay": 6}},
                       {"areas": {"nope": 3}}, {"items": {"pay_ontime": "5"}}, {"good": ["nope"]},
                       {"facts": {"insurance": "모름"}}, {"comment": "x" * 1001}, {"org": "x" * 81}):
            self.assertIsNone(review_items.clean_review({**self.GOOD, **change}), change)
        self.assertIsNone(review_items.clean_review([]))

    def test_record_review_stores_the_day_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = serve.open_reviews(Path(tmp) / "reviews.sqlite3")
            serve.record_review(conn, review_items.clean_review(self.GOOD))
            org, day = conn.execute("SELECT org, created_on FROM reviews").fetchone()
            conn.close()
        self.assertEqual(org, "경희대학교")
        self.assertRegex(day, r"^\d{4}-\d{2}-\d{2}$")


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
        body = json.dumps({"org": "A대학", "overall": 4}).encode()
        self.assertEqual(self.fetch("/test/api/review", body=body)[0], 401)
        self.assertEqual(self.fetch("/test/api/review", "pw", body)[0], 204)
        self.assertEqual(self.fetch("/test/api/review", "pw", b'{"org": "A"}')[0], 400)

    def test_no_password_set_means_no_test(self):
        self.handler.admin = None
        try:
            self.assertEqual(self.fetch("/test/index.html", "pw")[0], 404)
        finally:
            self.handler.admin = ("admin", "pw")


if __name__ == "__main__":
    unittest.main()
