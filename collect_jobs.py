#!/usr/bin/env python3
"""Collect Korean-language teaching job posts into SQLite."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html as html_lib
import html.parser
import json
import os
import re
import ssl
import sqlite3
import sys
import xml.etree.ElementTree as ET
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "jobs.sqlite3"
DEFAULT_SOURCES = ROOT / "sources.json"
DEFAULT_URL_FILE = ROOT / "seed_urls.txt"
DEFAULT_DISCOVERY_FILE = ROOT / "monitor_sources.json"
SAMPLE_HTML = ROOT / "sample_jobs.html"
NURI_LIST_URL = "https://nuri.iksi.or.kr/front/bbs/korlecturer/layout71/list.do?pageIndex={page}"
JINHAKPRO_LIST_URL = "https://www.jinhakpro.com/recruit/list?recruitTypeCode=L&page={page}"


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    trust: int
    kind: str
    title_hint: str | None = None
    institution_hint: str | None = None
    location_hint: str | None = None
    deadline_hint: str | None = None


@dataclass(frozen=True)
class Candidate:
    title: str
    url: str
    source: Source
    raw_text: str


@dataclass(frozen=True)
class DiscoverySource:
    name: str
    url: str
    trust: int
    kind: str
    pages: int = 1
    id_start: int | None = None
    id_end: int | None = None


class LinkTextParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.text_parts: list[str] = []
        self._active_href: str | None = None
        self._active_text: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._ignored_depth += 1
            return
        if tag.lower() == "a":
            attrs_map = {key.lower(): value for key, value in attrs if value is not None}
            self._active_href = attrs_map.get("href")
            self._active_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if tag.lower() == "a" and self._active_href:
            text = clean_text(" ".join(self._active_text))
            if text:
                self.links.append((text, self._active_href))
            self._active_href = None
            self._active_text = []

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if data.strip():
            self.text_parts.append(data)
        if self._active_href is not None:
            self._active_text.append(data)

    @property
    def text(self) -> str:
        return clean_text(" ".join(self.text_parts))


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold())


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            institution_name TEXT,
            source_name TEXT NOT NULL,
            source_url TEXT NOT NULL,
            original_url TEXT NOT NULL,
            location_text TEXT,
            deadline TEXT,
            posted_at TEXT,
            collected_at TEXT NOT NULL,
            description TEXT,
            raw_text TEXT,
            confidence_score INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'needs_review',
            review_note TEXT,
            reviewed_at TEXT,
            content_hash TEXT NOT NULL UNIQUE,
            duplicate_group_id TEXT
        )
        """
    )
    ensure_column(conn, "jobs", "review_note", "TEXT")
    ensure_column(conn, "jobs", "reviewed_at", "TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS collection_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            candidates INTEGER NOT NULL DEFAULT 0,
            saved INTEGER NOT NULL DEFAULT 0,
            updated INTEGER NOT NULL DEFAULT 0,
            skipped INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS source_errors (
            error_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER,
            source_name TEXT,
            source_url TEXT,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS discovery_state (
            source_name TEXT PRIMARY KEY,
            last_id INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    return conn


def get_discovery_last_id(conn: sqlite3.Connection, source_name: str) -> int | None:
    row = conn.execute(
        "SELECT last_id FROM discovery_state WHERE source_name = ?", (source_name,)
    ).fetchone()
    return int(row[0]) if row else None


def set_discovery_last_id(conn: sqlite3.Connection, source_name: str, last_id: int) -> None:
    conn.execute(
        """
        INSERT INTO discovery_state (source_name, last_id, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(source_name) DO UPDATE SET last_id = excluded.last_id, updated_at = excluded.updated_at
        """,
        (source_name, last_id, utc_now()),
    )


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def load_config(path: Path) -> tuple[list[str], list[str], list[str], list[str], list[Source]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    sources = [
        Source(
            name=item["name"],
            url=item["url"],
            trust=int(item.get("trust", 70)),
            kind=item.get("kind", "unknown"),
        )
        for item in data.get("sources", [])
    ]
    return (
        data.get("keywords", []),
        data.get("include_terms", []),
        data.get("hiring_terms", []),
        data.get("exclude_terms", []),
        sources,
    )


def fetch_url(url: str, timeout: int = 20) -> str:
    safe_url = urllib.parse.quote(url, safe=":/?&=%#@")
    request = urllib.request.Request(
        safe_url,
        headers={
            "User-Agent": "Mozilla/5.0 KoreanTeachingJobCollector/0.1 (+local research tool)"
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return decode_response(response)
    except urllib.error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return decode_response(response)


def decode_response(response: object) -> str:
    data = response.read()
    encodings = [response.headers.get_content_charset(), "utf-8", "cp949", "euc-kr"]
    candidates: list[str] = []
    for encoding in [item for item in encodings if item]:
        try:
            candidates.append(data.decode(encoding, errors="replace"))
        except LookupError:
            continue
    return min(candidates, key=lambda value: value.count("\ufffd")) if candidates else data.decode("utf-8", errors="replace")


def fetch_saramin(keyword: str, access_key: str, count: int) -> str:
    params = urllib.parse.urlencode(
        {
            "access-key": access_key,
            "keywords": keyword,
            "count": count,
            "sort": "pd",
        }
    )
    return fetch_url(f"https://oapi.saramin.co.kr/job-search?{params}")


def parse_html(html: str) -> LinkTextParser:
    parser = LinkTextParser()
    parser.feed(html)
    return parser


def extract_html_title(html: str, fallback_text: str, url: str) -> str:
    patterns = [
        r"<h1\b[^>]*>(.*?)</h1>",
        r"<h2\b[^>]*>(.*?)</h2>",
        r"<title\b[^>]*>(.*?)</title>",
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            title = clean_text(parse_html(match.group(1)).text)
            if title:
                return title[:180]
    guessed = guess_title(fallback_text)
    if guessed != "Untitled Korean teaching job":
        return guessed
    return urllib.parse.urlparse(url).netloc or guessed


def find_candidates_from_html(
    html: str,
    source: Source,
    include_terms: list[str],
    hiring_terms: list[str],
    sample_mode: bool = False,
) -> list[Candidate]:
    parsed = parse_html(html)
    candidates: list[Candidate] = []

    if sample_mode:
        article_chunks = re.findall(
            r"<article\b[^>]*>(.*?)</article>", html, flags=re.IGNORECASE | re.DOTALL
        )
        for chunk in article_chunks:
            article = parse_html(chunk)
            title_match = re.search(r"<h1\b[^>]*>(.*?)</h1>", chunk, flags=re.I | re.S)
            title = clean_text(parse_html(title_match.group(1)).text) if title_match else ""
            url = article.links[0][1] if article.links else source.url
            if is_relevant(title + " " + article.text, include_terms, hiring_terms, []):
                candidates.append(Candidate(title=title, url=url, source=source, raw_text=article.text))
        return candidates

    for text, href in parsed.links:
        combined = f"{text} {href}"
        if not is_relevant(combined, include_terms, hiring_terms, []):
            continue
        absolute_url = urllib.parse.urljoin(source.url, href)
        candidates.append(Candidate(title=text, url=absolute_url, source=source, raw_text=text))

    if not candidates and is_relevant(parsed.text, include_terms, hiring_terms, []):
        candidates.append(
            Candidate(
                title=guess_title(parsed.text),
                url=source.url,
                source=source,
                raw_text=parsed.text[:5000],
            )
        )

    return dedupe_candidates(candidates)


def is_relevant(
    text: str,
    include_terms: list[str],
    hiring_terms: list[str],
    exclude_terms: list[str],
) -> bool:
    lowered = text.casefold()
    include_hit = any(term.casefold() in lowered for term in include_terms)
    hiring_hit = any(term.casefold() in lowered for term in hiring_terms)
    exclude_hit = has_excluded_term(text, exclude_terms)
    return include_hit and hiring_hit and not exclude_hit


def has_excluded_term(text: str, exclude_terms: list[str]) -> bool:
    return any(matches_excluded_term(text, term) for term in exclude_terms)


def matches_excluded_term(text: str, term: str) -> bool:
    if term == "국어 강사":
        return re.search(r"(?<!한)국어\s*강사", text) is not None
    if term == "국어교사":
        return re.search(r"(?<!한)국어교사", text) is not None
    return term.casefold() in text.casefold()


def dedupe_candidates(candidates: Iterable[Candidate]) -> list[Candidate]:
    seen: set[str] = set()
    unique: list[Candidate] = []
    for candidate in candidates:
        key = normalize(candidate.title + candidate.url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def guess_title(text: str) -> str:
    sentence = re.split(r"[.!?\n。]", text, maxsplit=1)[0]
    return clean_text(sentence[:120]) or "Untitled Korean teaching job"


def enrich_candidate(
    candidate: Candidate,
    include_terms: list[str],
    hiring_terms: list[str],
    exclude_terms: list[str],
) -> dict[str, str | int | None]:
    detail_text = candidate.raw_text
    if has_excluded_term(candidate.title, exclude_terms):
        return {}
    if urllib.parse.urlparse(candidate.url).scheme in {"http", "https"}:
        try:
            detail_html = fetch_url(candidate.url)
            detail_text = parse_html(detail_html).text
        except Exception:
            detail_text = candidate.raw_text

    if not is_relevant(f"{candidate.title} {detail_text}", include_terms, hiring_terms, []):
        return {}

    deadline = extract_deadline(detail_text)
    institution = extract_institution(detail_text, candidate.title)
    location = extract_location(detail_text)
    content_hash = make_content_hash(candidate.title, institution, deadline, candidate.url)

    return {
        "title": candidate.title,
        "institution_name": institution,
        "source_name": candidate.source.name,
        "source_url": candidate.source.url,
        "original_url": candidate.url,
        "location_text": location,
        "deadline": deadline,
        "posted_at": extract_posted_at(detail_text),
        "collected_at": utc_now(),
        "description": detail_text[:4000],
        "raw_text": detail_text[:20000],
        "confidence_score": candidate.source.trust,
        "status": "needs_review",
        "content_hash": content_hash,
        "duplicate_group_id": content_hash[:16],
    }


def extract_deadline(text: str) -> str | None:
    patterns = [
        r"(?:모집종료일|접수\s*종료일|종료일)\s*[:：]?\s*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})",
        r"(?:마감일|접수\s*마감|지원\s*마감)\s*[:：]?\s*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})",
        r"(?:접수\s*기간|지원\s*기간|원서\s*접수\s*기간)\s*[:：]?\s*\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}.*?~\s*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})",
        r"(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})\s*(?:까지|마감)",
        r"(\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})\s*(?:까지|마감)",
        r"~\s*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})",
        r"~\s*(\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return normalize_date(match.group(1))
    if "채용시까지" in text or "상시" in text:
        return "rolling"
    return None


def is_active_deadline(deadline: str | None, today: dt.date) -> bool:
    if deadline == "rolling":
        return True
    if not deadline:
        return False
    try:
        return dt.date.fromisoformat(deadline) >= today
    except ValueError:
        return False


def prune_inactive_jobs(conn: sqlite3.Connection, today: dt.date) -> int:
    rows = conn.execute("SELECT job_id, deadline FROM jobs").fetchall()
    inactive_ids = [
        row[0]
        for row in rows
        if not is_active_deadline(row[1], today)
    ]
    if not inactive_ids:
        return 0
    placeholders = ", ".join("?" for _ in inactive_ids)
    conn.execute(f"DELETE FROM jobs WHERE job_id IN ({placeholders})", inactive_ids)
    return len(inactive_ids)


def refresh_existing_jobs(
    conn: sqlite3.Connection,
    run_id: int,
    today: dt.date,
    active_only: bool,
) -> dict[str, int]:
    """Re-fetch each already-saved job's own original_url to catch deadline
    changes (extensions, early closures). Title/institution/location are left
    untouched since they were already curated at first collection."""
    stats = {"candidates": 0, "saved": 0, "updated": 0, "skipped": 0, "failed": 0}
    rows = conn.execute(
        """
        SELECT job_id, title, institution_name, source_name, source_url, original_url
        FROM jobs
        WHERE status != 'rejected'
        """
    ).fetchall()
    for job_id, title, institution_name, source_name, source_url, original_url in rows:
        stats["candidates"] += 1
        source = Source(source_name, source_url, 0, "refresh")
        try:
            text = parse_html(fetch_url(original_url)).text
        except Exception as exc:
            stats["failed"] += 1
            log_error(conn, run_id, source, f"refresh {original_url}: {exc}")
            continue

        deadline = extract_deadline(text)
        if deadline is None:
            stats["skipped"] += 1
            continue

        if active_only and not is_active_deadline(deadline, today):
            conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            stats["updated"] += 1
            continue

        content_hash = make_content_hash(title, institution_name, deadline, original_url)
        job = {
            "original_url": original_url,
            "deadline": deadline,
            "collected_at": utc_now(),
            "description": text[:4000],
            "raw_text": text[:20000],
            "content_hash": content_hash,
            "duplicate_group_id": content_hash[:16],
        }
        save_job(conn, job)
        stats["updated"] += 1
    return stats


def extract_posted_at(text: str) -> str | None:
    match = re.search(r"(?:등록일|작성일|게시일)\s*[:：]?\s*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})", text)
    return normalize_date(match.group(1)) if match else None


def normalize_date(value: str) -> str:
    parts = re.split(r"[.\-/]", value.strip())
    if len(parts[0]) == 2:
        parts[0] = "20" + parts[0]
    year, month, day = (int(part) for part in parts[:3])
    return f"{year:04d}-{month:02d}-{day:02d}"


def extract_institution(text: str, title: str) -> str | None:
    patterns = [
        r"(?:작성자)\s*[:：]?\s*([가-힣A-Za-z0-9()·.\- ]{2,40})",
        r"(?:기관|기관명|채용기관|근무기관)\s*[:：]?\s*(.{2,80}?)(?=\s*(?:근무지|근무\s*지역|지역|주소|접수|마감일|지원\s*기간|기관\s*유형|대표전화|$))",
        r"([가-힣A-Za-z0-9()·.\- ]{2,40}(?:대학교|한국어학당|언어교육원|국제교육원|세종학당|문화원|교육원|센터))",
    ]
    for source_text in (text, title):
        for pattern in patterns:
            match = re.search(pattern, source_text)
            if match:
                return clean_text(match.group(1))[:80]
    return None


def extract_location(text: str) -> str | None:
    city_patterns = [
        (r"서울특별시|서울시", "서울"),
        (r"부산광역시|부산시", "부산"),
        (r"대구광역시|대구시", "대구"),
        (r"인천광역시|인천시", "인천"),
        (r"광주광역시|광주시", "광주"),
        (r"대전광역시|대전시", "대전"),
        (r"울산광역시|울산시", "울산"),
        (r"창원", "창원"),
    ]
    for pattern, city in city_patterns:
        if re.search(pattern, text):
            return city

    patterns = [
        r"(?:근무지|근무\s*지역|지역|주소)\s*[:：]?\s*(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주|창원|해외)",
        r"(?:근무지|근무\s*지역|지역|주소)\s*[:：]?\s*(.{2,80}?)(?=\s*(?:접수|마감일|지원\s*기간|기관|채용기관|채용상태|$))",
        r"(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주|해외)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return clean_text(match.group(1))[:100]
    return None


def clean_extracted_field(value: str | None, fallback: str | None) -> str | None:
    if not value:
        return fallback
    cleaned = clean_text(value).replace("\\n", " ")
    bad_markers = ["바로가기", "주메뉴", "본문", "메뉴"]
    if len(cleaned) > 45 or any(marker in cleaned for marker in bad_markers) or re.match(r"20\d{2}", cleaned):
        return fallback
    return cleaned


def make_content_hash(title: str, institution: str | None, deadline: str | None, url: str) -> str:
    stable = "|".join([normalize(title), normalize(institution or ""), deadline or ""])
    if not normalize(title) or not deadline:
        stable = f"{stable}|{normalize(url)}"
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def parse_saramin_jobs(xml_text: str, keyword: str) -> list[dict[str, str | int | None]]:
    root = ET.fromstring(xml_text)
    jobs: list[dict[str, str | int | None]] = []
    for item in root.findall(".//job"):
        title = clean_text(strip_markup(xml_get(item, "position/title") or "Untitled")
        )
        institution = clean_text(strip_markup(xml_get(item, "company/name") or ""))
        original_url = xml_get(item, "url") or ""
        location = clean_text(strip_markup(xml_get(item, "position/location/name") or ""))
        deadline = timestamp_to_date(xml_get(item, "expiration-timestamp"))
        posted_at = timestamp_to_date(xml_get(item, "posting-timestamp"))
        description_parts = [
            f"keyword: {keyword}",
            f"job-type: {strip_markup(xml_get(item, 'position/job-type/name') or '')}",
            f"industry: {strip_markup(xml_get(item, 'position/industry/name') or '')}",
            f"experience: {strip_markup(xml_get(item, 'position/experience-level/name') or '')}",
            f"education: {strip_markup(xml_get(item, 'position/required-education-level/name') or '')}",
        ]
        content_hash = make_content_hash(title, institution, deadline, original_url)
        jobs.append(
            {
                "title": title,
                "institution_name": institution or None,
                "source_name": "사람인 채용정보 API",
                "source_url": "https://oapi.saramin.co.kr/guide/info",
                "original_url": original_url,
                "location_text": location or None,
                "deadline": deadline,
                "posted_at": posted_at,
                "collected_at": utc_now(),
                "description": "\n".join(part for part in description_parts if part.split(": ", 1)[-1]),
                "raw_text": ET.tostring(item, encoding="unicode"),
                "confidence_score": 80,
                "status": "needs_review",
                "content_hash": content_hash,
                "duplicate_group_id": content_hash[:16],
            }
        )
    return jobs


def xml_get(item: ET.Element, path: str) -> str | None:
    found = item.find(path)
    return found.text if found is not None else None


def strip_markup(value: str) -> str:
    return clean_text(re.sub(r"<[^>]+>", "", value))


def timestamp_to_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        timestamp = int(value)
    except ValueError:
        return None
    if timestamp <= 0:
        return None
    return dt.datetime.fromtimestamp(timestamp, dt.UTC).date().isoformat()


def job_exists_for_url(conn: sqlite3.Connection, url: str) -> bool:
    return conn.execute("SELECT 1 FROM jobs WHERE original_url = ? LIMIT 1", (url,)).fetchone() is not None


def save_job(conn: sqlite3.Connection, job: dict[str, str | int | None]) -> str:
    existing = conn.execute(
        """
        SELECT job_id
        FROM jobs
        WHERE content_hash = ? OR original_url = ?
        ORDER BY CASE WHEN content_hash = ? THEN 0 ELSE 1 END, job_id
        LIMIT 1
        """,
        (job["content_hash"], job["original_url"], job["content_hash"]),
    ).fetchone()
    columns = list(job.keys())
    if existing:
        job_id = int(existing[0])
        conn.execute(
            "DELETE FROM jobs WHERE job_id <> ? AND (content_hash = ? OR original_url = ?)",
            (job_id, job["content_hash"], job["original_url"]),
        )
        assignments = ", ".join(f"{column}=?" for column in columns)
        conn.execute(
            f"UPDATE jobs SET {assignments} WHERE job_id = ?",
            [job[column] for column in columns] + [job_id],
        )
        return "updated"

    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO jobs ({', '.join(columns)}) VALUES ({placeholders})",
        [job[column] for column in columns],
    )
    return "saved"


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def start_run(conn: sqlite3.Connection) -> int:
    cursor = conn.execute("INSERT INTO collection_runs (started_at) VALUES (?)", (utc_now(),))
    return int(cursor.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, stats: dict[str, int]) -> None:
    conn.execute(
        """
        UPDATE collection_runs
        SET finished_at = ?, candidates = ?, saved = ?, updated = ?, skipped = ?, failed = ?
        WHERE run_id = ?
        """,
        (
            utc_now(),
            stats["candidates"],
            stats["saved"],
            stats["updated"],
            stats["skipped"],
            stats["failed"],
            run_id,
        ),
    )


def log_error(conn: sqlite3.Connection, run_id: int, source: Source, message: str) -> None:
    conn.execute(
        """
        INSERT INTO source_errors (run_id, source_name, source_url, message, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, source.name, source.url, message[:1000], utc_now()),
    )


def load_seed_urls(path: Path) -> list[Source]:
    if not path.exists():
        return []

    sources: list[Source] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.reader(line for line in handle if line.strip() and not line.lstrip().startswith("#")):
            if not row:
                continue
            url = row[0].strip()
            if not url:
                continue
            name = row[1].strip() if len(row) > 1 and row[1].strip() else infer_source_name(url)
            trust = int(row[2].strip()) if len(row) > 2 and row[2].strip().isdigit() else infer_trust(url)
            kind = row[3].strip() if len(row) > 3 and row[3].strip() else "seed_url"
            title_hint = row[4].strip() if len(row) > 4 and row[4].strip() else None
            institution_hint = row[5].strip() if len(row) > 5 and row[5].strip() else None
            location_hint = row[6].strip() if len(row) > 6 and row[6].strip() else None
            deadline_hint = row[7].strip() if len(row) > 7 and row[7].strip() else None
            sources.append(
                Source(
                    name=name,
                    url=url,
                    trust=trust,
                    kind=kind,
                    title_hint=title_hint,
                    institution_hint=institution_hint,
                    location_hint=location_hint,
                    deadline_hint=deadline_hint,
                )
            )
    return sources


def load_discovery_sources(path: Path) -> list[DiscoverySource]:
    if not path.exists():
        return []

    data = json.loads(path.read_text(encoding="utf-8"))
    sources: list[DiscoverySource] = []
    for item in data.get("sources", []):
        sources.append(
            DiscoverySource(
                name=item["name"],
                url=item["url"],
                trust=int(item.get("trust", 70)),
                kind=item.get("kind", "generic_links"),
                pages=int(item.get("pages", 1)),
                id_start=item.get("id_start"),
                id_end=item.get("id_end"),
            )
        )
    return sources


def infer_source_name(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
    return host or "seed url"


def infer_trust(url: str) -> int:
    host = urllib.parse.urlparse(url).netloc.lower()
    if any(token in host for token in [".ac.kr", ".go.kr", "ksif.or.kr", "korean.go.kr", "moe.go.kr"]):
        return 90
    if any(token in host for token in ["jinhakpro.com", "saramin.co.kr", "jobkorea.co.kr"]):
        return 75
    return 65


def collect_seed_urls(
    conn: sqlite3.Connection,
    run_id: int,
    seed_sources: list[Source],
    include_terms: list[str],
    hiring_terms: list[str],
    exclude_terms: list[str],
    today: dt.date,
    active_only: bool,
) -> dict[str, int]:
    stats = {"candidates": 0, "saved": 0, "updated": 0, "skipped": 0, "failed": 0}
    for source in seed_sources:
        if job_exists_for_url(conn, source.url):
            continue
        try:
            html = fetch_url(source.url)
            text = parse_html(html).text
            title = source.title_hint or extract_html_title(html, text, source.url)
            stats["candidates"] += 1
            if has_excluded_term(title, exclude_terms):
                stats["skipped"] += 1
                continue
            if not is_relevant(f"{title} {text}", include_terms, hiring_terms, []):
                stats["skipped"] += 1
                continue

            deadline = source.deadline_hint or extract_deadline(text)
            if active_only and not is_active_deadline(deadline, today):
                stats["skipped"] += 1
                continue
            institution = source.institution_hint or clean_extracted_field(extract_institution(text, title), source.name)
            location = source.location_hint or clean_extracted_field(extract_location(text), None)
            content_hash = make_content_hash(title, institution, deadline, source.url)
            job = {
                "title": title,
                "institution_name": institution,
                "source_name": source.name,
                "source_url": source.url,
                "original_url": source.url,
                "location_text": location,
                "deadline": deadline,
                "posted_at": extract_posted_at(text),
                "collected_at": utc_now(),
                "description": text[:4000],
                "raw_text": text[:20000],
                "confidence_score": source.trust,
                "status": "needs_review",
                "content_hash": content_hash,
                "duplicate_group_id": content_hash[:16],
            }
            result = save_job(conn, job)
            stats[result] += 1
        except Exception as exc:
            stats["failed"] += 1
            log_error(conn, run_id, source, str(exc))
    return stats


def collect_discovery_sources(
    conn: sqlite3.Connection,
    run_id: int,
    discovery_sources: list[DiscoverySource],
    include_terms: list[str],
    hiring_terms: list[str],
    exclude_terms: list[str],
    today: dt.date,
    active_only: bool,
) -> dict[str, int]:
    discovered: list[Source] = []
    stats = {"candidates": 0, "saved": 0, "updated": 0, "skipped": 0, "failed": 0}
    for source in discovery_sources:
        try:
            if source.kind == "kteacher_list":
                discovered.extend(discover_kteacher(source, today, active_only))
            elif source.kind == "jobkorea_mobile_list":
                discovered.extend(discover_jobkorea_mobile(source, today, active_only))
            elif source.kind == "hackers_mobile_probe":
                if source.id_start is None:
                    raise ValueError("hackers_mobile_probe source requires id_start")
                last_id = get_discovery_last_id(conn, source.name)
                start_id = source.id_start if last_id is None else max(source.id_start, last_id - 5)
                items, max_id_seen = discover_hackers_mobile(source, today, active_only, start_id)
                discovered.extend(items)
                if max_id_seen is not None:
                    set_discovery_last_id(conn, source.name, max(max_id_seen, last_id or 0))
            else:
                discovered.extend(discover_generic_links(source, include_terms, hiring_terms))
        except Exception as exc:
            stats["failed"] += 1
            log_error(conn, run_id, Source(source.name, source.url, source.trust, source.kind), str(exc))

    unique: dict[str, Source] = {}
    for item in discovered:
        if has_excluded_term(f"{item.title_hint or ''} {item.institution_hint or ''}", exclude_terms):
            continue
        if active_only and item.deadline_hint and not is_active_deadline(item.deadline_hint, today):
            continue
        unique.setdefault(item.url, item)

    seed_stats = collect_seed_urls(
        conn,
        run_id,
        list(unique.values()),
        include_terms,
        hiring_terms,
        exclude_terms,
        today,
        active_only,
    )
    for key, value in seed_stats.items():
        stats[key] += value
    return stats


def discover_generic_links(
    source: DiscoverySource, include_terms: list[str], hiring_terms: list[str]
) -> list[Source]:
    paginated = "{page}" in source.url
    pages = source.pages if paginated else 1
    items: list[Source] = []
    seen_hrefs: set[str] | None = None
    consecutive_empty_pages = 0
    for page in range(1, pages + 1):
        page_url = source.url.format(page=page) if paginated else source.url
        html = fetch_url(page_url)
        parsed = parse_html(html)

        page_hrefs = {href for _, href in parsed.links}
        if seen_hrefs is not None and page_hrefs == seen_hrefs:
            break
        seen_hrefs = page_hrefs

        page_items = 0
        for link_text, href in parsed.links:
            if not link_text:
                continue
            if urllib.parse.urlparse(href).scheme not in {"", "http", "https"}:
                continue
            if not is_relevant(f"{link_text} {href}", include_terms, hiring_terms, []):
                continue
            items.append(
                Source(
                    name=source.name,
                    url=urllib.parse.urljoin(page_url, href),
                    trust=source.trust,
                    kind="discovered_url",
                    title_hint=link_text[:180],
                )
            )
            page_items += 1

        if not paginated:
            continue
        consecutive_empty_pages = 0 if page_items else consecutive_empty_pages + 1
        if consecutive_empty_pages >= 3:
            break
    return items


def discover_kteacher(source: DiscoverySource, today: dt.date, active_only: bool) -> list[Source]:
    items: list[Source] = []
    for page in range(1, source.pages + 1):
        separator = "&" if "?" in source.url else "?"
        page_url = f"{source.url}{separator}pageNo={page}"
        html = fetch_url(page_url)
        rows = parse_kteacher_rows(html)
        if not rows:
            break
        active_count = 0
        for row in rows:
            if is_active_deadline(row["deadline"], today):
                active_count += 1
            if active_only and not is_active_deadline(row["deadline"], today):
                continue
            items.append(
                Source(
                    name=source.name,
                    url=urllib.parse.urljoin(page_url, f"/jobsearch/{row['id']}"),
                    trust=source.trust,
                    kind="discovered_kteacher",
                    title_hint=row["title"],
                    institution_hint=row["institution"],
                    location_hint="국외" if row["group"] == "국외" else None,
                    deadline_hint=row["deadline"],
                )
            )
        if active_only and active_count == 0:
            break
    return items


def parse_kteacher_rows(html: str) -> list[dict[str, str]]:
    desktop = html.split('<div class="text-center small mobileShow', 1)[0]
    rows: list[dict[str, str]] = []
    for row in re.findall(r"<tr>\s*(.*?)\s*</tr>", desktop, flags=re.DOTALL):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.DOTALL)
        if len(cells) != 6:
            continue
        link = re.search(r'href="/jobsearch/(\d+)"[^>]*>(.*?)</a>', cells[2], flags=re.DOTALL)
        if not link:
            continue
        rows.append(
            {
                "id": link.group(1),
                "group": html_clean(cells[1]),
                "title": html_clean(link.group(2)),
                "institution": html_clean(cells[3]),
                "deadline": normalize_date(html_clean(cells[5])),
            }
        )
    return rows


def discover_jobkorea_mobile(source: DiscoverySource, today: dt.date, active_only: bool) -> list[Source]:
    items: list[Source] = []
    for page in range(1, source.pages + 1):
        separator = "&" if "?" in source.url else "?"
        page_url = f"{source.url}{separator}page={page}"
        html = fetch_url(page_url)
        rows = parse_jobkorea_mobile_rows(html)
        if not rows:
            break
        for row in rows:
            if active_only and not is_active_deadline(row["deadline"], today):
                continue
            if not any(term in row["title"] for term in ["한국어", "TOPIK", "토픽"]):
                continue
            items.append(
                Source(
                    name=source.name,
                    url=urllib.parse.urljoin(page_url, row["url"]),
                    trust=source.trust,
                    kind="discovered_jobkorea",
                    title_hint=row["title"],
                    institution_hint=row["institution"],
                    location_hint=row["location"],
                    deadline_hint=row["deadline"],
                )
            )
    return items


def parse_jobkorea_mobile_rows(html: str) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    for item in re.findall(r'<li class="devAgiWrap.*?</li>', html, flags=re.DOTALL):
        company = re.search(r'<div class="company">(.*?)</div>', item, flags=re.DOTALL)
        title = re.search(r'<div class="title">(.*?)</div>', item, flags=re.DOTALL)
        link = re.search(r'<a href="([^"]+)"', item)
        meta = re.search(r'<div class="item">\s*(.*?)\s*</div>', item, flags=re.DOTALL)
        if not company or not title or not link:
            continue
        meta_text = html_clean(meta.group(1)) if meta else ""
        rows.append(
            {
                "institution": html_clean(company.group(1)),
                "title": html_clean(title.group(1)),
                "url": html_lib.unescape(link.group(1)),
                "location": extract_jobkorea_location(meta_text),
                "deadline": extract_jobkorea_deadline(meta_text),
            }
        )
    return rows


def extract_jobkorea_deadline(meta_text: str) -> str | None:
    if "상시채용" in meta_text:
        return "rolling"
    match = re.search(r"~\s*(\d{1,2})/(\d{1,2})", meta_text)
    if not match:
        return None
    return f"{dt.date.today().year:04d}-{int(match.group(1)):02d}-{int(match.group(2)):02d}"


def extract_jobkorea_location(meta_text: str) -> str | None:
    match = re.search(r"(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주|해외|재택)", meta_text)
    return match.group(1) if match else None


def discover_hackers_mobile(
    source: DiscoverySource,
    today: dt.date,
    active_only: bool,
    start_id: int,
    max_consecutive_misses: int = 25,
    max_ids_per_run: int = 400,
) -> tuple[list[Source], int | None]:
    """Scan job_view.php by numeric id, since the list page requires login.

    If source.id_end is set, scan exactly that fixed range (legacy/manual mode).
    Otherwise scan forward from start_id and stop once max_consecutive_misses
    ids in a row have no posting, so id_end never needs manual upkeep.
    """
    if source.id_end is not None:
        id_range: Iterable[int] = range(start_id, source.id_end + 1)
        open_ended = False
    else:
        id_range = range(start_id, start_id + max_ids_per_run)
        open_ended = True

    items: list[Source] = []
    max_id_seen: int | None = None
    consecutive_misses = 0
    for item_id in id_range:
        url = source.url.format(id=item_id)
        try:
            text = parse_html(fetch_url(url, timeout=8)).text
            match = re.search(r"채용공고 제목\s+(.+?)\s+모집 마감일\s+([0-9/]+)", text)
        except Exception:
            match = None
        if not match:
            consecutive_misses += 1
            if open_ended and consecutive_misses >= max_consecutive_misses:
                break
            continue

        consecutive_misses = 0
        max_id_seen = item_id
        title = clean_text(match.group(1))
        deadline = normalize_date(match.group(2))
        if "한국어" not in title and "TOPIK" not in title and "토픽" not in title:
            continue
        if active_only and not is_active_deadline(deadline, today):
            continue
        items.append(
            Source(
                name=source.name,
                url=url,
                trust=source.trust,
                kind="discovered_hackers",
                title_hint=title,
                institution_hint=extract_bracketed_institution(title),
                location_hint=extract_location(text) or infer_location_from_text(text),
                deadline_hint=deadline,
            )
        )
    return items, max_id_seen


def extract_bracketed_institution(title: str) -> str | None:
    match = re.match(r"\[([^\]]+)\]", title)
    return clean_text(match.group(1)) if match else None


def html_clean(value: str) -> str:
    return clean_text(html_lib.unescape(re.sub(r"<[^>]+>", " ", value)))


def collect_nuri_ksi(
    conn: sqlite3.Connection,
    run_id: int,
    pages: int,
    include_terms: list[str],
    hiring_terms: list[str],
    exclude_terms: list[str],
    today: dt.date,
    active_only: bool,
) -> dict[str, int]:
    stats = {"candidates": 0, "saved": 0, "updated": 0, "skipped": 0, "failed": 0}
    source = Source(
        "누리 세종학당 한국어 교원 모집",
        "https://nuri.iksi.or.kr/front/bbs/korlecturer/layout71/list.do",
        85,
        "public_list",
    )
    for page in range(1, pages + 1):
        page_url = NURI_LIST_URL.format(page=page)
        try:
            text = parse_html(fetch_url(page_url)).text
            rows = parse_nuri_rows(text)
            stats["candidates"] += len(rows)
            active_rows_on_page = 0
            for row in rows:
                title = row["title"]
                institution = row["institution"]
                deadline = row["deadline"]
                if active_only and not is_active_deadline(deadline, today):
                    stats["skipped"] += 1
                    continue
                active_rows_on_page += 1
                item_url = f"{page_url}#nuri-{row['number']}"
                combined = f"{title} {institution}"
                if has_excluded_term(combined, exclude_terms):
                    stats["skipped"] += 1
                    continue
                if not is_relevant(combined, include_terms, hiring_terms, []):
                    stats["skipped"] += 1
                    continue
                content_hash = make_content_hash(title, institution, deadline, item_url)
                job = {
                    "title": title,
                    "institution_name": institution,
                    "source_name": source.name,
                    "source_url": page_url,
                    "original_url": item_url,
                    "location_text": infer_location_from_text(combined),
                    "deadline": deadline,
                    "posted_at": row["start_date"],
                    "collected_at": utc_now(),
                    "description": (
                        f"누리 세종학당 한국어 교원 모집 목록 수집\n"
                        f"모집번호: {row['number']}\n"
                        f"기관: {institution}\n"
                        f"모집기간: {row['start_date']} ~ {row['deadline']}\n"
                        f"조회수: {row['views']}"
                    ),
                    "raw_text": json.dumps(row, ensure_ascii=False),
                    "confidence_score": source.trust,
                    "status": "needs_review",
                    "content_hash": content_hash,
                    "duplicate_group_id": content_hash[:16],
                }
                result = save_job(conn, job)
                stats[result] += 1
            if active_only and rows and active_rows_on_page == 0:
                break
        except Exception as exc:
            stats["failed"] += 1
            log_error(conn, run_id, source, f"page {page}: {exc}")
    return stats


def collect_jinhakpro_list(
    conn: sqlite3.Connection,
    run_id: int,
    pages: int,
    include_terms: list[str],
    hiring_terms: list[str],
    exclude_terms: list[str],
    today: dt.date,
    active_only: bool,
) -> dict[str, int]:
    stats = {"candidates": 0, "saved": 0, "updated": 0, "skipped": 0, "failed": 0}
    source = Source(
        "진학프로 강사 목록",
        "https://www.jinhakpro.com/recruit/list?recruitTypeCode=L",
        75,
        "job_board_list",
    )
    seen_urls: set[str] = set()
    for page in range(1, pages + 1):
        page_url = JINHAKPRO_LIST_URL.format(page=page)
        try:
            html = fetch_url(page_url)
            links = parse_html(html).links
            recruit_links = [
                (text, urllib.parse.urljoin(page_url, href))
                for text, href in links
                if "/recruit/" in href and "공고 스크랩" not in text
            ]
            if not recruit_links:
                break
            for link_text, url in recruit_links:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                stats["candidates"] += 1
                if not is_relevant(link_text, include_terms, hiring_terms, []):
                    stats["skipped"] += 1
                    continue
                if has_excluded_term(link_text, exclude_terms):
                    stats["skipped"] += 1
                    continue
                try:
                    detail_text = parse_html(fetch_url(url)).text
                    job = build_jinhakpro_job(detail_text, url, source)
                    if active_only and not is_active_deadline(str(job.get("deadline") or ""), today):
                        stats["skipped"] += 1
                        continue
                    if not is_relevant(
                        f"{job['title']} {job.get('institution_name') or ''} {detail_text}",
                        include_terms,
                        hiring_terms,
                        [],
                    ):
                        stats["skipped"] += 1
                        continue
                    result = save_job(conn, job)
                    stats[result] += 1
                except Exception as exc:
                    stats["failed"] += 1
                    log_error(conn, run_id, source, f"{url}: {exc}")
        except Exception as exc:
            stats["failed"] += 1
            log_error(conn, run_id, source, f"page {page}: {exc}")
    return stats


def build_jinhakpro_job(text: str, url: str, source: Source) -> dict[str, str | int | None]:
    institution, title = extract_jinhakpro_heading(text)
    title = title or guess_title(text)
    deadline = extract_deadline(text)
    location = extract_jinhakpro_location(text) or infer_location_from_text(text)
    content_hash = make_content_hash(title, institution, deadline, url)
    return {
        "title": title,
        "institution_name": institution,
        "source_name": source.name,
        "source_url": source.url,
        "original_url": url,
        "location_text": location,
        "deadline": deadline,
        "posted_at": None,
        "collected_at": utc_now(),
        "description": text[:4000],
        "raw_text": text[:20000],
        "confidence_score": source.trust,
        "status": "needs_review",
        "content_hash": content_hash,
        "duplicate_group_id": content_hash[:16],
    }


def extract_jinhakpro_heading(text: str) -> tuple[str | None, str | None]:
    page_title = re.match(r"(?P<title>.+?)\s+-\s+(?P<institution>.+?)\s+\|\s+진학프로", text)
    if page_title:
        return clean_text(page_title.group("institution")), clean_text(page_title.group("title"))

    match = re.search(
        r"(?P<institution>[가-힣A-Za-z0-9().·\s]{2,60})\s+"
        r"(?P<title>.+?)\s+"
        r"(?:접수중|마감)\s+\d{4}\.\d{2}\.\d{2}\s*~\s*\d{4}\.\d{2}\.\d{2}",
        text,
    )
    if not match:
        return None, None

    institution = clean_text(match.group("institution"))
    title = clean_text(match.group("title"))
    institution = re.sub(r"^.*(?:메뉴|채용 정보)\s+", "", institution).strip()
    institution = re.sub(r"^(?:전체|전임|비전임|강사|연구원)\s+", "", institution).strip()
    return institution or None, title or None


def extract_jinhakpro_location(text: str) -> str | None:
    match = re.search(r"근무 지역\s*(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주|해외)", text)
    return match.group(1) if match else None


def parse_nuri_rows(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    pattern = re.compile(
        r"Number\s+(?P<number>\d+)\s+Title\s+(?P<title>.+?)\s+"
        r"Name of Institution\s+(?P<institution>.+?)\s+"
        r"Recruitment Period\s+(?P<start>\d{4}-\d{2}-\d{2})\s+~\s+"
        r"(?P<end>\d{4}-\d{2}-\d{2})\s+Views\s+(?P<views>\d+)"
    )
    for match in pattern.finditer(text):
        rows.append(
            {
                "number": match.group("number"),
                "title": clean_text(match.group("title")),
                "institution": clean_text(match.group("institution")),
                "start_date": match.group("start"),
                "deadline": match.group("end"),
                "views": match.group("views"),
            }
        )
    if rows:
        return rows

    table_start = text.find("Number Recruitment Information Name of Institution Recruitment Period Views")
    if table_start < 0:
        return rows
    table_text = text[table_start:]
    fallback_pattern = re.compile(
        r"(?P<number>\d{3,5})\s+(?P<title>.+?)\s+(?P<institution>[가-힣A-Za-z0-9()·.\- ]{2,50})\s+"
        r"(?P<start>\d{4}-\d{2}-\d{2})\s+~\s+(?P<end>\d{4}-\d{2}-\d{2})\s+(?P<views>\d+)"
    )
    for match in fallback_pattern.finditer(table_text):
        rows.append(
            {
                "number": match.group("number"),
                "title": clean_text(match.group("title")),
                "institution": clean_text(match.group("institution")),
                "start_date": match.group("start"),
                "deadline": match.group("end"),
                "views": match.group("views"),
            }
        )
    return rows


def infer_location_from_text(text: str) -> str | None:
    campuses = [
        ("서울", "서울"),
        ("다빈치", "경기"),
        ("대구", "대구"),
        ("경산", "경북"),
        ("천안", "충남"),
        ("전북", "전북"),
        ("전주", "전북"),
        ("포항", "경북"),
        ("아주대학교", "경기"),
        ("중앙대학교", "서울"),
        ("백석대학교", "충남"),
    ]
    for token, location in campuses:
        if token in text:
            return location
    return extract_location(text)


def collect_saramin(
    conn: sqlite3.Connection,
    run_id: int,
    keywords: list[str],
    include_terms: list[str],
    hiring_terms: list[str],
    exclude_terms: list[str],
    count: int,
    today: dt.date,
    active_only: bool,
) -> dict[str, int]:
    stats = {"candidates": 0, "saved": 0, "updated": 0, "skipped": 0, "failed": 0}
    access_key = os.environ.get("SARAMIN_ACCESS_KEY")
    source = Source(
        "사람인 채용정보 API",
        "https://oapi.saramin.co.kr/guide/info",
        80,
        "api",
    )
    if not access_key:
        return stats

    for keyword in keywords:
        try:
            xml_text = fetch_saramin(keyword, access_key, count)
            jobs = parse_saramin_jobs(xml_text, keyword)
            stats["candidates"] += len(jobs)
            for job in jobs:
                text = f"{job['title']} {job.get('institution_name') or ''} {job.get('description') or ''}"
                if has_excluded_term(str(job["title"]), exclude_terms):
                    stats["skipped"] += 1
                    continue
                if active_only and not is_active_deadline(str(job.get("deadline") or ""), today):
                    stats["skipped"] += 1
                    continue
                if not is_relevant(text, include_terms + keywords, hiring_terms, []):
                    stats["skipped"] += 1
                    continue
                result = save_job(conn, job)
                stats[result] += 1
        except Exception as exc:
            stats["failed"] += 1
            log_error(conn, run_id, source, f"{keyword}: {exc}")
    return stats


def collect(args: argparse.Namespace) -> int:
    keywords, include_terms, hiring_terms, exclude_terms, sources = load_config(Path(args.sources))
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    if args.sample:
        sample_url = SAMPLE_HTML.as_uri()
        sources = [Source("local sample", sample_url, 100, "sample")]

    conn = init_db(Path(args.db))
    if args.active_only and not args.sample:
        prune_inactive_jobs(conn, today)
    run_id = start_run(conn)
    stats = {"candidates": 0, "saved": 0, "updated": 0, "skipped": 0, "failed": 0}

    try:
        if not args.sample:
            if args.refresh:
                refresh_stats = refresh_existing_jobs(conn, run_id, today, args.active_only)
                for key, value in refresh_stats.items():
                    stats[key] += value

            if args.jinhakpro_pages > 0:
                jinhakpro_stats = collect_jinhakpro_list(
                    conn,
                    run_id,
                    args.jinhakpro_pages,
                    include_terms + keywords,
                    hiring_terms,
                    exclude_terms,
                    today,
                    args.active_only,
                )
                for key, value in jinhakpro_stats.items():
                    stats[key] += value

            if args.nuri_pages > 0:
                nuri_stats = collect_nuri_ksi(
                    conn,
                    run_id,
                    args.nuri_pages,
                    include_terms + keywords,
                    hiring_terms,
                    exclude_terms,
                    today,
                    args.active_only,
                )
                for key, value in nuri_stats.items():
                    stats[key] += value

            discovery_sources = load_discovery_sources(Path(args.discovery_file))
            if discovery_sources:
                discovery_stats = collect_discovery_sources(
                    conn,
                    run_id,
                    discovery_sources,
                    include_terms + keywords,
                    hiring_terms,
                    exclude_terms,
                    today,
                    args.active_only,
                )
                for key, value in discovery_stats.items():
                    stats[key] += value

            seed_stats = collect_seed_urls(
                conn,
                run_id,
                load_seed_urls(Path(args.url_file)),
                include_terms + keywords,
                hiring_terms,
                exclude_terms,
                today,
                args.active_only,
            )
            for key, value in seed_stats.items():
                stats[key] += value

            saramin_stats = collect_saramin(
                conn,
                run_id,
                keywords,
                include_terms,
                hiring_terms,
                exclude_terms,
                args.saramin_count,
                today,
                args.active_only,
            )
            for key, value in saramin_stats.items():
                stats[key] += value

        for source in sources:
            try:
                html = SAMPLE_HTML.read_text(encoding="utf-8") if args.sample else fetch_url(source.url)
                candidates = find_candidates_from_html(
                    html,
                    source,
                    include_terms + keywords,
                    hiring_terms,
                    sample_mode=args.sample,
                )
                stats["candidates"] += len(candidates)
                for candidate in candidates:
                    job = enrich_candidate(candidate, include_terms + keywords, hiring_terms, exclude_terms)
                    if not job:
                        stats["skipped"] += 1
                        continue
                    if args.active_only and not is_active_deadline(str(job.get("deadline") or ""), today):
                        stats["skipped"] += 1
                        continue
                    result = save_job(conn, job)
                    stats[result] += 1
            except Exception as exc:
                stats["failed"] += 1
                log_error(conn, run_id, source, str(exc))
        finish_run(conn, run_id, stats)
        conn.commit()
    finally:
        conn.close()

    print(
        "\n".join(
            [
                f"run_id={run_id}",
                f"candidates={stats['candidates']}",
                f"saved={stats['saved']}",
                f"updated={stats['updated']}",
                f"skipped={stats['skipped']}",
                f"failed={stats['failed']}",
                f"db={Path(args.db).resolve()}",
            ]
        )
    )
    return 0 if stats["failed"] == 0 else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Korean teaching job posts.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    parser.add_argument("--sources", default=str(DEFAULT_SOURCES), help="Source config JSON path")
    parser.add_argument("--url-file", default=str(DEFAULT_URL_FILE), help="CSV seed URL file")
    parser.add_argument(
        "--discovery-file",
        default=str(DEFAULT_DISCOVERY_FILE),
        help="Discovery source config JSON path (auto list/id-range crawlers)",
    )
    parser.add_argument("--sample", action="store_true", help="Use local sample_jobs.html")
    parser.add_argument("--nuri-pages", type=int, default=126, help="Nuri KSI list pages to collect")
    parser.add_argument("--jinhakpro-pages", type=int, default=1, help="JinhakPro lecturer list pages to collect")
    parser.add_argument("--today", default=None, help="Active-period reference date, YYYY-MM-DD")
    parser.add_argument("--include-expired", dest="active_only", action="store_false", help="Keep expired or undated jobs")
    parser.add_argument(
        "--no-refresh",
        dest="refresh",
        action="store_false",
        help="Skip re-fetching already-saved jobs' own URLs to catch deadline changes",
    )
    parser.set_defaults(active_only=True, refresh=True)
    parser.add_argument("--saramin-count", type=int, default=50, help="Saramin jobs per keyword")
    return parser


if __name__ == "__main__":
    sys.exit(collect(build_parser().parse_args()))
