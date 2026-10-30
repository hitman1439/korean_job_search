#!/usr/bin/env python3
"""Serve the built site and count how many browsers saved each job.

The site stays static apart from one endpoint, POST /api/save
{"job": "123", "client": "<32 hex>", "on": true}. The client id is random and
made by the browser itself, so a count means "browsers that saved this job and
still have it saved"; nothing about the visitor is kept.

/test/ serves the admin-only staging build (site_test/, from build_site.py
--test) behind HTTP Basic auth with ADMIN_USER / ADMIN_PASSWORD from
secrets.env. Without a password set, /test does not exist. Reviews sent from
/test/review.html land in reviews.sqlite3 with the day only, no visitor data.

  python serve.py                      # serve site/ on 127.0.0.1:8080
  python serve.py --report             # print save counts per job
  python serve.py --reviews            # print 기관 평가 per institution
"""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import hmac
import json
import os
import re
import sqlite3
import sys
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import review_items


ROOT = Path(__file__).resolve().parent
DEFAULT_SITE = ROOT / "site"
DEFAULT_STATS = ROOT / "stats.sqlite3"
DEFAULT_JOBS = ROOT / "jobs.sqlite3"
DEFAULT_TEST = ROOT / "site_test"
DEFAULT_REVIEWS = ROOT / "reviews.sqlite3"
DEFAULT_SECRETS = ROOT / "secrets.env"
TEST_PREFIX = "/test"

JOB_ID = re.compile(r"\d{1,9}")
CLIENT_ID = re.compile(r"[0-9a-f]{32}")
MAX_BODY = 512
# One browser cannot inflate the table past this many jobs.
MAX_JOBS_PER_CLIENT = 300
MAX_REVIEW_BODY = 16_384


def open_stats(path: Path) -> sqlite3.Connection:
    # The stats live apart from jobs.sqlite3 so a running collector never
    # blocks a save.
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS saves (
            client TEXT NOT NULL,
            job_id INTEGER NOT NULL,
            saved INTEGER NOT NULL,
            first_saved_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (client, job_id)
        )
        """
    )
    return conn


def record_save(conn: sqlite3.Connection, client: str, job_id: int, on: bool) -> bool:
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    known = conn.execute("SELECT 1 FROM saves WHERE client = ? AND job_id = ?", (client, job_id)).fetchone()
    if not known:
        if not on:
            return True
        (count,) = conn.execute("SELECT COUNT(*) FROM saves WHERE client = ?", (client,)).fetchone()
        if count >= MAX_JOBS_PER_CLIENT:
            return False
    conn.execute(
        """
        INSERT INTO saves (client, job_id, saved, first_saved_at, updated_at) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (client, job_id) DO UPDATE SET saved = excluded.saved, updated_at = excluded.updated_at
        """,
        (client, job_id, 1 if on else 0, now, now),
    )
    conn.commit()
    return True


def parse_save(body: bytes) -> tuple[str, int, bool] | None:
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    job, client, on = str(data.get("job", "")), str(data.get("client", "")), data.get("on")
    if not JOB_ID.fullmatch(job) or not CLIENT_ID.fullmatch(client) or not isinstance(on, bool):
        return None
    return client, int(job), on


def open_reviews(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY,
            org TEXT NOT NULL,
            overall INTEGER NOT NULL,
            data TEXT NOT NULL,
            created_on TEXT NOT NULL
        )
        """
    )
    return conn


def record_review(conn: sqlite3.Connection, review: dict) -> None:
    # The day only: a time stamp could single out who sent it.
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    conn.execute(
        "INSERT INTO reviews (org, overall, data, created_on) VALUES (?, ?, ?, ?)",
        (review["org"], review["overall"], json.dumps(review, ensure_ascii=False), today),
    )
    conn.commit()


def load_admin(secrets: Path) -> tuple[str, str] | None:
    """ADMIN_USER / ADMIN_PASSWORD from the environment, else from secrets.env."""
    values = {k: os.environ[k] for k in ("ADMIN_USER", "ADMIN_PASSWORD") if os.environ.get(k)}
    if secrets.is_file():
        for line in secrets.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key.strip() in ("ADMIN_USER", "ADMIN_PASSWORD"):
                values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    if not values.get("ADMIN_PASSWORD"):
        return None
    return values.get("ADMIN_USER") or "admin", values["ADMIN_PASSWORD"]


def check_basic_auth(header: str | None, admin: tuple[str, str]) -> bool:
    scheme, _, encoded = (header or "").partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        user, sep, password = base64.b64decode(encoded.strip(), validate=True).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return False
    # Compare both in full so the time taken says nothing about which was wrong.
    ok_user = hmac.compare_digest(user.encode(), admin[0].encode())
    ok_password = hmac.compare_digest(password.encode(), admin[1].encode())
    return bool(sep) and ok_user and ok_password


def test_path(raw: str) -> str | None:
    """The path inside the test build for a /test URL, else None."""
    path = unquote(urlsplit(raw).path)
    if path == TEST_PREFIX or path.startswith(TEST_PREFIX + "/"):
        return path[len(TEST_PREFIX):] or "/"
    return None


class Handler(SimpleHTTPRequestHandler):
    stats_path: Path = DEFAULT_STATS
    reviews_path: Path = DEFAULT_REVIEWS
    test_dir: Path = DEFAULT_TEST
    admin: tuple[str, str] | None = None

    def end_headers(self) -> None:
        # Admin pages must never sit in a shared cache (Cloudflare, proxies).
        if test_path(self.path) is not None:
            self.send_header("Cache-Control", "no-store, private")
        super().end_headers()

    def translate_path(self, path: str) -> str:
        inner = test_path(path)
        if inner is None:
            return super().translate_path(path)
        site = self.directory
        self.directory = str(self.test_dir)
        try:
            return super().translate_path(inner)
        finally:
            self.directory = site

    def admin_gate(self) -> bool:
        """For /test URLs: True if the request may go on; otherwise the reply is sent."""
        if test_path(self.path) is None:
            return True
        if not self.admin:
            self.send_error(HTTPStatus.NOT_FOUND)
            return False
        if not check_basic_auth(self.headers.get("Authorization"), self.admin):
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Basic realm="admin", charset="UTF-8"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        if urlsplit(self.path).path == TEST_PREFIX:
            self.send_response(HTTPStatus.MOVED_PERMANENTLY)
            self.send_header("Location", TEST_PREFIX + "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        return True

    def do_GET(self) -> None:
        if self.admin_gate():
            super().do_GET()

    def do_HEAD(self) -> None:
        if self.admin_gate():
            super().do_HEAD()

    def read_body(self, limit: int) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length <= 0 or length > limit:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return None
        return self.rfile.read(length)

    def do_POST(self) -> None:
        route = urlsplit(self.path).path
        if route == TEST_PREFIX + "/api/review":
            if self.admin_gate():
                self.post_review()
            return
        if route != "/api/save":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = self.read_body(MAX_BODY)
        if body is None:
            return
        parsed = parse_save(body)
        if not parsed:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        conn = open_stats(self.stats_path)
        try:
            ok = record_save(conn, *parsed)
        finally:
            conn.close()
        self.send_response(HTTPStatus.NO_CONTENT if ok else HTTPStatus.TOO_MANY_REQUESTS)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def post_review(self) -> None:
        body = self.read_body(MAX_REVIEW_BODY)
        if body is None:
            return
        try:
            review = review_items.clean_review(json.loads(body))
        except (ValueError, UnicodeDecodeError):
            review = None
        if not review:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        conn = open_reviews(self.reviews_path)
        try:
            record_review(conn, review)
        finally:
            conn.close()
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Content-Length", "0")
        self.end_headers()


def report(stats_path: Path, jobs_path: Path) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if not stats_path.is_file():
        print("no saves yet (stats.sqlite3 does not exist)")
        return 0
    conn = open_stats(stats_path)
    rows = conn.execute(
        """
        SELECT job_id, SUM(saved), COUNT(*), MAX(updated_at) FROM saves
        GROUP BY job_id ORDER BY SUM(saved) DESC, COUNT(*) DESC, job_id
        """
    ).fetchall()
    (browsers,) = conn.execute("SELECT COUNT(DISTINCT client) FROM saves").fetchone()
    conn.close()
    titles: dict[int, str] = {}
    if jobs_path.is_file():
        jobs = sqlite3.connect(f"file:{jobs_path}?mode=ro", uri=True)
        for job_id, org, title in jobs.execute("SELECT job_id, institution_name, title FROM jobs"):
            titles[job_id] = " · ".join(x for x in (org, title) if x)
        jobs.close()
    print(f"browsers that ever saved a job: {browsers}")
    print(f"{'job':>5} {'now':>4} {'ever':>4}  last change           title")
    for job_id, now, ever, last in rows:
        print(f"{job_id:>5} {now:>4} {ever:>4}  {last}  {titles.get(job_id, '')[:60]}")
    return 0


def report_reviews(reviews_path: Path) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if not reviews_path.is_file():
        print("no reviews yet (reviews.sqlite3 does not exist)")
        return 0
    conn = open_reviews(reviews_path)
    rows = conn.execute("SELECT org, data FROM reviews ORDER BY org, id").fetchall()
    conn.close()
    by_org: dict[str, list[dict]] = {}
    for org, data in rows:
        by_org.setdefault(org, []).append(json.loads(data))
    chips = {key: chip for key, _, chip, _ in review_items.AREAS}
    for org, reviews in sorted(by_org.items(), key=lambda kv: -len(kv[1])):
        overall = sum(r["overall"] for r in reviews) / len(reviews)
        print(f"{org}  평가 {len(reviews)}개 · 첫인상 {overall:.1f}")
        areas = []
        for key, chip in chips.items():
            scores = [r["areas"][key] for r in reviews if key in r["areas"]]
            if scores:
                areas.append(f"{chip} {sum(scores) / len(scores):.1f}({len(scores)})")
        if areas:
            print("  " + " · ".join(areas))
        for r in reviews:
            if r.get("comment"):
                print(f"  - {r['comment'][:120]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the built site and count job saves")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--site", default=str(DEFAULT_SITE), help="Built site folder")
    parser.add_argument("--stats", default=str(DEFAULT_STATS), help="Save-count database")
    parser.add_argument("--db", default=str(DEFAULT_JOBS), help="Jobs database, for titles in --report")
    parser.add_argument("--test-site", default=str(DEFAULT_TEST), help="Admin-only staging build served at /test/")
    parser.add_argument("--reviews-db", default=str(DEFAULT_REVIEWS), help="기관 평가 database")
    parser.add_argument("--secrets", default=str(DEFAULT_SECRETS), help="KEY=value file with ADMIN_PASSWORD")
    parser.add_argument("--report", action="store_true", help="Print save counts and exit")
    parser.add_argument("--reviews", action="store_true", help="Print 기관 평가 per institution and exit")
    args = parser.parse_args(argv)

    if args.report:
        return report(Path(args.stats), Path(args.db))
    if args.reviews:
        return report_reviews(Path(args.reviews_db))
    site = Path(args.site)
    if not (site / "index.html").is_file():
        print(f"error: no built site at {site.resolve()}; run python build_site.py first", file=sys.stderr)
        return 1
    Handler.stats_path = Path(args.stats)
    open_stats(Handler.stats_path).close()
    Handler.reviews_path = Path(args.reviews_db)
    Handler.test_dir = Path(args.test_site)
    Handler.admin = load_admin(Path(args.secrets))
    if not Handler.admin:
        print("note: ADMIN_PASSWORD is not set, so /test is off", file=sys.stderr)
    elif not (Handler.test_dir / "index.html").is_file():
        print(f"note: no test build at {Handler.test_dir.resolve()}; run python build_site.py --test", file=sys.stderr)
    server = ThreadingHTTPServer((args.bind, args.port), partial(Handler, directory=str(site)))
    print(f"serving {site.resolve()} on http://{args.bind}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
