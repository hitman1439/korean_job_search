"""Tests for the save counter in serve.py."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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


if __name__ == "__main__":
    unittest.main()
