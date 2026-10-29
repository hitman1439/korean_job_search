#!/usr/bin/env python3
"""Local review UI for collected Korean teaching jobs."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "jobs.sqlite3"
UI_DIR = ROOT / "ui"


def ensure_db(db_path: Path) -> None:
    import collect_jobs

    conn = collect_jobs.init_db(db_path)
    conn.commit()
    conn.close()


JOB_COLUMNS = """
    job_id, title, institution_name, source_name, source_url,
    original_url, location_text, deadline, posted_at, collected_at,
    description, confidence_score, latitude, longitude, address, place_name,
    status, review_note, reviewed_at, is_canonical, duplicate_group_id,
    institution_type, country, is_overseas, qualification, experience_required,
    newcomer_ok, demo_lesson, salary_text, benefits, summary, fields_source
"""


def row_to_dict(cursor: sqlite3.Cursor, row: sqlite3.Row) -> dict[str, object]:
    return {description[0]: row[index] for index, description in enumerate(cursor.description)}


class ReviewHandler(BaseHTTPRequestHandler):
    db_path = DEFAULT_DB

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.serve_file(UI_DIR / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/styles.css":
            self.serve_file(UI_DIR / "styles.css", "text/css; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self.serve_file(UI_DIR / "app.js", "text/javascript; charset=utf-8")
            return
        if parsed.path == "/api/jobs":
            self.send_json(self.get_jobs(parse_qs(parsed.query)))
            return
        if parsed.path == "/api/config":
            self.send_json(self.get_config())
            return
        if parsed.path == "/api/summary":
            self.send_json(self.get_summary())
            return
        if parsed.path == "/api/runs":
            self.send_json(self.get_runs())
            return
        if parsed.path == "/api/errors":
            self.send_json(self.get_errors())
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/review"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "jobs":
                self.update_review(parts[2])
                return
        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: object) -> None:
        return

    def serve_file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: object) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        data = self.rfile.read(length)
        return json.loads(data.decode("utf-8"))

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_jobs(self, query: dict[str, list[str]]) -> dict[str, object]:
        search = query.get("q", [""])[0].strip()
        status = query.get("status", [""])[0].strip()
        source = query.get("source", [""])[0].strip()
        include_expired = query.get("include_expired", [""])[0] == "1"
        limit = min(int(query.get("limit", ["200"])[0]), 500)

        clauses: list[str] = []
        params: list[object] = []
        if search:
            clauses.append(
                "(title LIKE ? OR institution_name LIKE ? OR location_text LIKE ? OR description LIKE ?)"
            )
            like = f"%{search}%"
            params.extend([like, like, like, like])
        if status:
            clauses.append("status = ?")
            params.append(status)
        if source:
            clauses.append("source_name = ?")
            params.append(source)
        if not include_expired:
            # Closed postings stay in the DB until the next run prunes them.
            clauses.append("(deadline IS NULL OR deadline = 'rolling' OR deadline >= ?)")
            params.append(dt.date.today().isoformat())

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT {JOB_COLUMNS}
            FROM jobs
            {where}
            ORDER BY
                CASE WHEN deadline IS NULL THEN 1 ELSE 0 END,
                deadline ASC,
                collected_at DESC
            LIMIT ?
        """
        params.append(limit)
        with self.connect() as conn:
            cursor = conn.execute(sql, params)
            rows = [row_to_dict(cursor, row) for row in cursor.fetchall()]
        return {"jobs": rows}

    def update_review(self, job_id_text: str) -> None:
        try:
            job_id = int(job_id_text)
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid job id")
            return

        try:
            payload = self.read_json()
        except json.JSONDecodeError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON")
            return

        status = str(payload.get("status", "")).strip()
        note = str(payload.get("review_note", "")).strip()
        if status not in {"needs_review", "approved", "rejected"}:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid status")
            return

        reviewed_at = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = ?, review_note = ?, reviewed_at = ?
                WHERE job_id = ?
                """,
                (status, note or None, reviewed_at, job_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                self.send_error(HTTPStatus.NOT_FOUND, "Job not found")
                return
            row = conn.execute(f"SELECT {JOB_COLUMNS} FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        self.send_json({"job": dict(row)})

    def get_config(self) -> dict[str, object]:
        """Hand the browser the Kakao JavaScript key so the map tab can load."""
        import collect_jobs

        collect_jobs.load_secrets_file()
        return {"kakao_js_key": os.environ.get("KAKAO_JS_KEY") or ""}

    def get_summary(self) -> dict[str, object]:
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            by_status = [
                dict(row)
                for row in conn.execute(
                    "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status ORDER BY count DESC"
                )
            ]
            by_source = [
                dict(row)
                for row in conn.execute(
                    "SELECT source_name, COUNT(*) AS count FROM jobs GROUP BY source_name ORDER BY count DESC"
                )
            ]
            latest_run = conn.execute(
                """
                SELECT run_id, started_at, finished_at, candidates, saved, updated, skipped, failed
                FROM collection_runs
                ORDER BY run_id DESC
                LIMIT 1
                """
            ).fetchone()
        return {
            "total": total,
            "by_status": by_status,
            "by_source": by_source,
            "latest_run": dict(latest_run) if latest_run else None,
        }

    def get_runs(self) -> dict[str, object]:
        with self.connect() as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT run_id, started_at, finished_at, candidates, saved,
                           updated, skipped, failed
                    FROM collection_runs
                    ORDER BY run_id DESC
                    LIMIT 20
                    """
                )
            ]
        return {"runs": rows}

    def get_errors(self) -> dict[str, object]:
        with self.connect() as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT error_id, run_id, source_name, source_url, message, created_at
                    FROM source_errors
                    ORDER BY error_id DESC
                    LIMIT 50
                    """
                )
            ]
        return {"errors": rows}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local job review UI.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8765, help="Bind port")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    db_path = Path(args.db).resolve()
    ensure_db(db_path)
    ReviewHandler.db_path = db_path
    server = ThreadingHTTPServer((args.host, args.port), ReviewHandler)
    print(f"Review UI: http://{args.host}:{args.port}")
    print(f"DB: {db_path}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
