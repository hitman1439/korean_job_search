"""Tests for the content-completeness gate: a posting with a missing notice file
or an empty notice never reaches the public site.

Run from the project root:  python -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_site as bs  # noqa: E402
import collect_jobs as cj  # noqa: E402

PDF = b"%PDF-1.7\n" + b"0" * 2000
HWP = b"\xd0\xcf\x11\xe0" + b"0" * 2000
HTML = b"<!doctype html><html><body>login required</body></html>" + b" " * 2000


class FileCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel: str, data: bytes) -> str:
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return rel

    def test_real_documents_pass(self):
        self.assertTrue(bs.file_ok(self.dir / self.write("1/1.pdf", PDF)))
        self.assertTrue(bs.file_ok(self.dir / self.write("1/2.hwp", HWP)))

    def test_error_page_empty_and_missing_fail(self):
        self.assertFalse(bs.file_ok(self.dir / self.write("1/1.pdf", HTML)))
        self.assertFalse(bs.file_ok(self.dir / self.write("1/2.pdf", b"%PDF")))
        self.assertFalse(bs.file_ok(self.dir / "1/3.pdf"))

    def test_collector_refuses_the_same(self):
        self.assertTrue(cj.looks_like_document(PDF, ".pdf"))
        self.assertFalse(cj.looks_like_document(HTML, ".hwp"))
        self.assertFalse(cj.looks_like_document(PDF, ".txt"))

    def job(self, body: str, files: list[tuple[str, str]], listed: int | None = None) -> dict:
        return {"body_text": body, "files": files, "listed_files": len(files) if listed is None else listed}

    def test_whole_posting_has_no_holds(self):
        rel = self.write("5/1.pdf", PDF)
        job = self.job("## 모집 내용\n자세한 내용은 첨부파일을 참조하세요.", [("공고문.pdf", rel)])
        self.assertEqual(bs.content_holds(job, self.dir), [])
        self.assertEqual(job["files"], [("공고문.pdf", rel)])

    def test_empty_body_is_held(self):
        self.assertEqual(bs.content_holds(self.job("  ", []), self.dir), ["공고 본문 없음"])

    def test_unmirrored_or_broken_file_is_held(self):
        broken = self.write("6/1.pdf", HTML)
        job = self.job("모집합니다.", [("공고문.pdf", broken)], listed=2)
        self.assertEqual(bs.content_holds(job, self.dir), ["첨부파일 2개를 받지 못함"])
        self.assertEqual(job["files"], [])

    def test_body_pointing_at_missing_file_is_held(self):
        for body in ("자세한 내용은 첨부파일을 참고하시기 바랍니다.", "붙임 1. 채용 공고문", "## 첨부\n- 지원서", "별첨 양식 참조"):
            with self.subTest(body=body):
                self.assertEqual(bs.content_holds(self.job(body, []), self.dir),
                                 ["본문이 첨부파일을 가리키는데 파일이 없음"])

    def test_applicant_attaching_documents_is_not_a_hold(self):
        body = "이력서와 자기소개서를 첨부하여 이메일로 보내 주세요."
        self.assertEqual(bs.content_holds(self.job(body, []), self.dir), [])

    def test_saramin_postings_are_not_checked(self):
        self.assertEqual(bs.content_holds({"external": True, "files": []}, self.dir), [])


if __name__ == "__main__":
    unittest.main()
