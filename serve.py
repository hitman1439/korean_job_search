#!/usr/bin/env python3
"""Serve the built site and count how many browsers saved each job.

The site stays static apart from one endpoint, POST /api/save
{"job": "123", "client": "<32 hex>", "on": true}. The client id is random and
made by the browser itself, so a count means "browsers that saved this job and
still have it saved"; nothing about the visitor is kept.

  python serve.py                      # serve site/ on 127.0.0.1:8080
  python serve.py --report             # print save counts per job
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sqlite3
import sys
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_SITE = ROOT / "site"
DEFAULT_STATS = ROOT / "stats.sqlite3"
DEFAULT_JOBS = ROOT / "jobs.sqlite3"

JOB_ID = re.compile(r"\d{1,9}")
CLIENT_ID = re.compile(r"[0-9a-f]{32}")
MAX_BODY = 512
# One browser cannot inflate the table past this many jobs.
MAX_JOBS_PER_CLIENT = 300


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


class Handler(SimpleHTTPRequestHandler):
    stats_path: Path = DEFAULT_STATS

    def do_POST(self) -> None:
        if self.path.split("?")[0] != "/api/save":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length <= 0 or length > MAX_BODY:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        parsed = parse_save(self.rfile.read(length))
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the built site and count job saves")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--site", default=str(DEFAULT_SITE), help="Built site folder")
    parser.add_argument("--stats", default=str(DEFAULT_STATS), help="Save-count database")
    parser.add_argument("--db", default=str(DEFAULT_JOBS), help="Jobs database, for titles in --report")
    parser.add_argument("--report", action="store_true", help="Print save counts and exit")
    args = parser.parse_args(argv)

    if args.report:
        return report(Path(args.stats), Path(args.db))
    site = Path(args.site)
    if not (site / "index.html").is_file():
        print(f"error: no built site at {site.resolve()}; run python build_site.py first", file=sys.stderr)
        return 1
    Handler.stats_path = Path(args.stats)
    open_stats(Handler.stats_path).close()
    server = ThreadingHTTPServer((args.bind, args.port), partial(Handler, directory=str(site)))
    print(f"serving {site.resolve()} on http://{args.bind}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
