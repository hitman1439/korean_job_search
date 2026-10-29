#!/usr/bin/env python3
"""Collect Korean-language teaching job posts into SQLite."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html as html_lib
import html.parser
import http.cookiejar
import json
import os
import re
import ssl
import sqlite3
import sys
import threading
import time
import xml.etree.ElementTree as ET
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import extract_fields
from extract_fields import COUNTRY_NAMES


ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "jobs.sqlite3"
DEFAULT_SOURCES = ROOT / "sources.json"
DEFAULT_FILES_DIR = ROOT / "files"
DEFAULT_URL_FILE = ROOT / "seed_urls.txt"
DEFAULT_DISCOVERY_FILE = ROOT / "monitor_sources.json"
SAMPLE_HTML = ROOT / "sample_jobs.html"
NURI_LIST_URL = "https://nuri.iksi.or.kr/front/bbs/korlecturer/layout71/list.do?pageIndex={page}"
JINHAKPRO_LIST_URL = "https://www.jinhakpro.com/recruit/list?recruitTypeCode=L&page={page}"

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
DEFAULT_SECRETS_FILE = ROOT / "secrets.env"
# Minimum gap between two requests to the same host. Boards we read are small
# institutional sites; back-to-back detail fetches got Jinhakpro to answer 429.
MIN_REQUEST_INTERVAL = 1.0
# A posting whose deadline could not be read is kept for review this long after
# it was first seen, then dropped. Overseas notices often state the deadline in
# a form the parser misses, and dropping them outright lost most of them.
UNDATED_GRACE_DAYS = 45
ROLLING_MAX_DAYS = 90
KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
KAKAO_ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"


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
    posted_at_hint: str | None = None
    body_hint: str | None = None
    attachments_hint: tuple[tuple[str, str], ...] = ()


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
    terms: tuple[str, ...] = ()


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
    ensure_column(conn, "jobs", "latitude", "REAL")
    ensure_column(conn, "jobs", "longitude", "REAL")
    ensure_column(conn, "jobs", "address", "TEXT")
    ensure_column(conn, "jobs", "place_name", "TEXT")
    # collected_at moves on every refresh; first_seen_at is the undated-job clock.
    ensure_column(conn, "jobs", "first_seen_at", "TEXT")
    ensure_column(conn, "jobs", "is_canonical", "INTEGER NOT NULL DEFAULT 1")
    # Notice files (JSON [{name, url}]) and the best link to apply through,
    # which may differ from original_url when that is an aggregator board.
    ensure_column(conn, "jobs", "attachments", "TEXT")
    ensure_column(conn, "jobs", "apply_url", "TEXT")
    ensure_column(conn, "jobs", "apply_url_source", "TEXT")
    for column, definition in JOB_FIELD_COLUMNS:
        ensure_column(conn, "jobs", column, definition)
    conn.execute("UPDATE jobs SET first_seen_at = collected_at WHERE first_seen_at IS NULL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS geocode_cache (
            query TEXT PRIMARY KEY,
            latitude REAL,
            longitude REAL,
            address TEXT,
            place_name TEXT,
            looked_up_at TEXT NOT NULL
        )
        """
    )
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
    # Posts already found closed. University boards keep years of old notices
    # on the pages we scan; without this every run would re-open all of them.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS closed_urls (
            url TEXT PRIMARY KEY,
            deadline TEXT,
            checked_at TEXT NOT NULL
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


# Structured fields filled by extract_fields.py (rules, optionally the LLM).
JOB_FIELD_COLUMNS = [
    ("institution_type", "TEXT"),
    ("country", "TEXT"),
    ("is_overseas", "INTEGER"),
    ("qualification", "TEXT"),
    ("experience_required", "TEXT"),
    ("newcomer_ok", "INTEGER"),
    ("demo_lesson", "INTEGER"),
    ("salary_text", "TEXT"),
    ("benefits", "TEXT"),
    ("apply_email", "TEXT"),
    ("work_period", "TEXT"),
    ("work_hours", "TEXT"),
    ("documents", "TEXT"),
    ("how_to_apply", "TEXT"),
    ("schedule", "TEXT"),
    ("contact", "TEXT"),
    # The whole notice, cleaned of the hosting board's menus and name (Claude).
    ("body_text", "TEXT"),
    ("summary", "TEXT"),
    ("fields_source", "TEXT"),
    ("fields_extracted_at", "TEXT"),
]


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


def load_secrets_file(path: Path = DEFAULT_SECRETS_FILE) -> None:
    """Load KEY=value lines from a gitignored file into the environment.

    Keeps site credentials out of the repo and out of shell history. Values
    already set in the real environment win, so a one-off override still works.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def build_session_opener() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [
        ("User-Agent", BROWSER_USER_AGENT),
        ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        ("Accept-Language", "ko-KR,ko;q=0.9"),
    ]
    return opener


_LAST_REQUEST_AT: dict[str, float] = {}
# Hosts that want a gentler pace than MIN_REQUEST_INTERVAL.
HOST_INTERVAL = {"www.jinhakpro.com": 3.0}
# Hosts that kept answering 429 this run: no more requests to them until the
# next run. Waiting out a block one post at a time once stalled a run for an hour.
_BLOCKED_HOSTS: set[str] = set()


class HostRateLimited(Exception):
    """The host is rate-limiting this run; skip its remaining requests."""


def wait_for_host(url: str) -> None:
    """Space out requests to one host by MIN_REQUEST_INTERVAL (or HOST_INTERVAL) seconds."""
    host = urllib.parse.urlparse(url).hostname or ""
    last = _LAST_REQUEST_AT.get(host)
    if last is not None:
        remaining = HOST_INTERVAL.get(host, MIN_REQUEST_INTERVAL) - (time.monotonic() - last)
        if remaining > 0:
            time.sleep(remaining)
    _LAST_REQUEST_AT[host] = time.monotonic()


def open_with_opener(opener: urllib.request.OpenerDirector, request: str | urllib.request.Request, timeout: int) -> str:
    wait_for_host(request if isinstance(request, str) else request.full_url)
    with opener.open(request, timeout=timeout) as response:
        return decode_response(response)


RATE_LIMIT_RETRIES = 3


def fetch_url(url: str, timeout: int = 20) -> str:
    """Fetch a page, backing off when the site rate-limits us (HTTP 429).

    Jinhakpro answers 429 once a run fires its detail requests back to back,
    which used to drop those postings for the whole run.
    """
    host = urllib.parse.urlparse(url).hostname or ""
    if host in _BLOCKED_HOSTS:
        raise HostRateLimited(f"{host} is rate-limiting this run")
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            return with_deadline(fetch_url_once, (url, timeout), timeout * 3)
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                raise
            if attempt == RATE_LIMIT_RETRIES:
                _BLOCKED_HOSTS.add(host)
                print(f"warning: {host} keeps answering 429; skipping it for the rest of this run", file=sys.stderr)
                raise HostRateLimited(f"{host} is rate-limiting this run") from exc
            retry_after = exc.headers.get("Retry-After", "")
            delay = int(retry_after) if retry_after.isdigit() else 5 * (attempt + 1)
            time.sleep(min(delay, 60))
    raise AssertionError("unreachable")


def with_deadline(func, args: tuple, seconds: float):
    """Run func(*args) but give up after `seconds` in total.

    The socket timeout bounds each read, not the whole request: a run once sat
    for ten minutes on one half-closed Jinhakpro connection. The worker thread
    is left behind as a daemon; the run moves on.
    """
    outcome: dict = {}

    def run() -> None:
        try:
            outcome["value"] = func(*args)
        except BaseException as exc:  # handed to the caller below
            outcome["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise TimeoutError(f"no complete response within {seconds:.0f}s")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


def fetch_url_once(url: str, timeout: int) -> str:
    safe_url = urllib.parse.quote(url, safe=":/?&=%#@")
    wait_for_host(safe_url)
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
        # Several university boards serve incomplete certificate chains. Retry
        # without verification, but say so: this must never pass silently.
        print(f"warning: TLS verification skipped for {safe_url}", file=sys.stderr)
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


SPACED_YMD = re.compile(r"(\d{4})\s*[년年]\s*(\d{1,2})\s*[월月]\s*(\d{1,2})\s*[일日]")
SPACED_DOTTED = re.compile(r"(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})")


def compact_spaced_dates(text: str) -> str:
    """Rewrite loosely spaced Korean dates into the plain dotted form.

    Notices pasted out of HWP wrap every run in its own tag, so the text comes
    through as "2026 년 8 월 26 일" or "2026. 8. 26." and the deadline patterns
    below never fire. Normalising first lets one set of patterns cover both.
    """
    text = SPACED_YMD.sub(r"\1.\2.\3", text)
    return SPACED_DOTTED.sub(r"\1.\2.\3", text)


EMPLOYMENT_PERIOD = re.compile(r"(?:근무|계약|임용|고용|재직|사업|교육|연수)\s*기간")
# A bare "~ date" is only trusted when the words just before it are about applying.
APPLICATION_CONTEXT = re.compile(r"접수|모집|지원|원서|서류|제출|공고\s*기간")

MONTHS = {
    name: index
    for index, names in enumerate(
        [
            ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
            ("may",), ("june", "jun"), ("july", "jul"), ("august", "aug"),
            ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for name in names
}
_MONTH = r"(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)\.?"
EN_DATE_MDY = re.compile(_MONTH + r"\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?", re.I)
EN_DATE_DMY = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+" + _MONTH + r",?\s+(\d{4})", re.I)
EN_DEADLINE_LABEL = re.compile(
    r"(?:application\s+deadline|deadline(?:\s+(?:to|for)\s+appl(?:y|ications))?|closing\s+date|close\s+date"
    r"|apply\s+(?:by|before)|applications?\s+(?:are\s+|must\s+be\s+(?:received|submitted)\s+)?(?:due|by)"
    r"|review\s+of\s+applications\s+(?:will\s+)?(?:begin|begins|start|starts|commence|commences)"
    r"|priority\s+(?:deadline|consideration)|next\s+review\s+date|review\s+date)"
    r"\s*(?:is|on|by|:|：)?\s*",
    re.I,
)
UNTIL_FILLED = re.compile(r"until\s+(?:the\s+)?position\s+is\s+filled|open\s+until\s+filled", re.I)


def parse_english_date(text: str, reference: dt.date) -> str | None:
    """Read "November 15, 2026", "15 Nov 2026" or "11/15/2026" at the start of text.

    A month-and-day with no year ("will start on November 15") takes the year
    that puts it nearest after the reference date.
    """
    # "Monday, Nov 2, 2026" - drop a leading weekday.
    text = re.sub(r"^(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s*", "", text[:60], flags=re.I)
    iso = re.match(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
    if iso:
        return normalize_date(iso.group(0))
    us = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if us:
        return safe_date(int(us.group(3)), int(us.group(1)), int(us.group(2)))
    dmy = EN_DATE_DMY.match(text)
    if dmy:
        return safe_date(int(dmy.group(3)), MONTHS[dmy.group(2).lower()], int(dmy.group(1)))
    mdy = EN_DATE_MDY.match(text)
    if mdy:
        month, day = MONTHS[mdy.group(1).lower()], int(mdy.group(2))
        if mdy.group(3):
            return safe_date(int(mdy.group(3)), month, day)
        year = reference.year
        guess = safe_date(year, month, day)
        if guess and dt.date.fromisoformat(guess) < reference - dt.timedelta(days=180):
            guess = safe_date(year + 1, month, day)
        return guess
    return None


def safe_date(year: int, month: int, day: int) -> str | None:
    try:
        return dt.date(year, month, day).isoformat()
    except ValueError:
        return None


def extract_deadline(text: str, reference: dt.date | None = None) -> str | None:
    reference = reference or dt.date.today()
    text = compact_spaced_dates(text)
    patterns = [
        r"(?:모집종료일|접수\s*종료일|종료일)\s*[:：]?\s*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})",
        r"(?:마감일|접수\s*마감|지원\s*마감)\s*[:：]?\s*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})",
        # Japanese / Chinese notices on overseas boards.
        r"(?:応募締切|締め?切り?|応募期限|〆切|截止日期|截止)\s*(?:日)?\s*[:：]?\s*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})",
        r"(?:접수\s*기간|지원\s*기간|원서\s*접수\s*기간)\s*[:：|]?\s*\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}.*?~\s*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})",
        # Boards that print a two-digit year range, e.g. "접수기간 | 26.08.25~26.09.08".
        r"(?:접수\s*기간|지원\s*기간|원서\s*접수\s*기간)\s*[:：|]?\s*\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}\s*~\s*(\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})",
        r"(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})\s*(?:까지|마감)",
        r"(\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})\s*(?:까지|마감)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return normalize_date(match.group(1))
    for label in EN_DEADLINE_LABEL.finditer(text):
        found = parse_english_date(text[label.end() :], reference)
        if found:
            return found
    # A bare "~ date" is only a guess. Take it only when the words just before
    # it are about applying, and never for ranges that describe how long the
    # job lasts (근무기간 2026.9.1. ~ 2027.8.31.).
    for pattern in (
        r"~\s*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})",
        r"~\s*(\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})",
    ):
        for match in re.finditer(pattern, text):
            before = text[max(0, match.start() - 40) : match.start()]
            if EMPLOYMENT_PERIOD.search(before) or not APPLICATION_CONTEXT.search(before):
                continue
            return normalize_date(match.group(1))
    if re.search(r"채용\s*시\s*까지|채용\s*시\s*마감|상시\s*(?:모집|채용)|수시\s*(?:모집|채용)|채용까지", text):
        return "rolling"
    if UNTIL_FILLED.search(text):
        return "rolling"
    return None


def is_active_deadline(deadline: str | None, today: dt.date) -> bool:
    """Whether a posting is still open. An unknown deadline counts as open:
    prune_inactive_jobs drops undated postings after UNDATED_GRACE_DAYS."""
    if deadline == "rolling" or not deadline:
        return True
    try:
        return dt.date.fromisoformat(deadline) >= today
    except ValueError:
        return True


def is_live_job(deadline: str | None, posted_at: str | None, first_seen_at: str | None, today: dt.date) -> bool:
    """An undated posting stays for UNDATED_GRACE_DAYS after it was posted, or
    after we first saw it when the board shows no posting date. A rolling
    ("상시") posting stays ROLLING_MAX_DAYS: boards rarely take them down."""
    started = posted_at or first_seen_at
    age = (today - dt.date.fromisoformat(started[:10])).days if started else 0
    if deadline == "rolling":
        return age <= ROLLING_MAX_DAYS
    if deadline:
        return is_active_deadline(deadline, today)
    return age <= UNDATED_GRACE_DAYS


def prune_inactive_jobs(conn: sqlite3.Connection, today: dt.date) -> int:
    rows = conn.execute("SELECT job_id, deadline, posted_at, first_seen_at FROM jobs").fetchall()
    inactive_ids = [
        row[0]
        for row in rows
        if not is_live_job(row[1], row[2], row[3], today)
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
        SELECT job_id, title, institution_name, source_name, source_url, original_url, posted_at
        FROM jobs
        WHERE status != 'rejected'
        """
    ).fetchall()
    for job_id, title, institution_name, source_name, source_url, original_url, posted_at in rows:
        stats["candidates"] += 1
        source = Source(source_name, source_url, 0, "refresh")
        try:
            page = parse_html(fetch_url(original_url))
            text = page.text
        except Exception as exc:
            stats["failed"] += 1
            log_error(conn, run_id, source, f"refresh {original_url}: {exc}")
            continue
        # Fill in notice files for rows saved before they were collected. Only
        # when found: some boards (IAKLE) list them only in their AJAX view.
        files = extract_attachments(page.links, original_url)
        if files:
            conn.execute("UPDATE jobs SET attachments = ? WHERE job_id = ?", (attachments_json(files), job_id))

        deadline = extract_deadline(text, today)
        if deadline is None:
            # Give the prune step the best evidence of the post's age: keep
            # the earlier of the stored and the inferred posting date.
            inferred = infer_posted_at(text, title, today)
            if inferred and (posted_at is None or inferred < posted_at):
                conn.execute("UPDATE jobs SET posted_at = ? WHERE job_id = ?", (inferred, job_id))
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


ANY_DATE = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")
TITLE_YEAR = re.compile(r"(20\d{2})\s*(?:년|학년도|-|\s)")
SEMESTER = re.compile(r"(봄|여름|가을|겨울)\s*(?:·\s*\S+\s*)?학기")
SEMESTER_START = {"봄": 3, "여름": 6, "가을": 9, "겨울": 12}


def infer_posted_at(text: str, title: str, today: dt.date) -> str | None:
    """When a post went up, for boards that print no 작성일 label.

    University boards keep years of notices, many without a deadline line we
    can read; first-seen would make a 2017 notice look new. The latest full
    date in the body bounds the post's age: if every date is past, the post
    is at least that old. A future date means the notice still runs, so no
    guess. A past year in the title ("2024학년도 겨울학기") counts too.
    """
    labeled = extract_posted_at(text)
    if labeled:
        return labeled
    # "2026학년도 여름학기 강사 모집" seen in October: that term has started,
    # so its hiring is over even though the year is this year.
    title_year = TITLE_YEAR.search(title)
    term = SEMESTER.search(title)
    if term and title_year and int(title_year.group(1)) == today.year:
        start = dt.date(today.year, SEMESTER_START[term.group(1)], 1)
        if today >= start:
            return (start - dt.timedelta(days=1)).isoformat()
    dates = []
    for year, month, day in ANY_DATE.findall(strip_site_chrome(text)):
        try:
            dates.append(dt.date(int(year), int(month), int(day)))
        except ValueError:
            continue
    if dates and max(dates) > today:
        return None
    evidence = [max(dates)] if dates else []
    if title_year and int(title_year.group(1)) < today.year:
        evidence.append(dt.date(int(title_year.group(1)), 12, 31))
    return min(evidence).isoformat() if evidence else None


def normalize_date(value: str) -> str:
    value = value.strip()
    # Some boards print compact dates ("20260907") with no separators.
    compact = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", value)
    if compact:
        value = "-".join(compact.groups())
    parts = re.split(r"[.\-/]", value)
    if len(parts[0]) == 2:
        parts[0] = "20" + parts[0]
    year, month, day = (int(part) for part in parts[:3])
    return f"{year:04d}-{month:02d}-{day:02d}"


# Board accounts that post on behalf of others; as 작성자 they name nobody.
BOARD_ADMIN_NAMES = {"운영자", "관리자", "admin", "administrator"}


def extract_institution(text: str, title: str) -> str | None:
    patterns = [
        # KLEOcean-style posts lead with "회사명 : X 근무지역 : ..."; only trusted with a colon.
        r"회사명\s*[:：]\s*(.{2,80}?)(?=\s*(?:근무\s*지역|근무지|고용형태|마감일|$))",
        r"(?:작성자)\s*[:：]?\s*([가-힣A-Za-z0-9()·.\- ]{2,40})",
        r"(?:기관|기관명|채용기관|근무기관)\s*[:：]?\s*(.{2,80}?)(?=\s*(?:근무지|근무\s*지역|지역|주소|접수|마감일|지원\s*기간|기관\s*유형|대표전화|$))",
        r"([가-힣A-Za-z0-9()·.\- ]{2,40}(?:대학교|한국어학당|언어교육원|국제교육원|세종학당|문화원|교육원|센터))",
    ]
    for source_text in (strip_site_chrome(text), title):
        for pattern in patterns:
            match = re.search(pattern, source_text)
            if not match:
                continue
            # The author field runs straight into "작성일 2026-..." on most boards.
            value = clean_text(re.split(r"\s*(?:작성일|등록일|조회)", match.group(1))[0])
            if value.lower() in BOARD_ADMIN_NAMES:
                continue
            return tidy_institution(value)[:80]
    return None


INSTITUTION_UNIT = r"(?:언어연구교육원|언어교육원|한국어교육원|국제교육원|한국어학당|어학당|한국어교육센터|언어교육센터|국제교육센터|교육센터|센터|교육원)"
UNIVERSITY_WITH_UNIT = re.compile(rf"[가-힣A-Za-z]+(?:대학교|대학)(?:\s*\([^)]*\))?(?:\s+[가-힣A-Za-z]*{INSTITUTION_UNIT})?")


def tidy_institution(value: str) -> str:
    """Trim the run-on text the suffix pattern drags in.

    "가을 · 겨울학기 이화여자대학교 언어교육원" -> "이화여자대학교 언어교육원";
    "연세대학교 한국어학당 한국어강사 모집 공고 연세대학교 …" -> "연세대학교 한국어학당".
    """
    match = UNIVERSITY_WITH_UNIT.search(value)
    return match.group(0) if match else value


REGION_NAMES = "서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주"
# Full province/city names as they appear in addresses -> the short region name.
REGION_ALIASES = [
    (r"서울특별시|서울시", "서울"),
    (r"부산광역시|부산시", "부산"),
    (r"대구광역시|대구시", "대구"),
    (r"인천광역시|인천시", "인천"),
    # "광주시" alone is also 경기도 광주시, so only the metropolitan form counts.
    (r"광주광역시", "광주"),
    (r"대전광역시|대전시", "대전"),
    (r"울산광역시|울산시", "울산"),
    (r"세종특별자치시|세종시", "세종"),
    (r"경기도", "경기"),
    (r"강원특별자치도|강원도", "강원"),
    (r"충청북도", "충북"),
    (r"충청남도", "충남"),
    (r"전북특별자치도|전라북도", "전북"),
    (r"전라남도", "전남"),
    (r"경상북도", "경북"),
    (r"경상남도|창원시?", "경남"),
    (r"제주특별자치도|제주도", "제주"),
]
# Markers that open a site footer. The footer carries the *posting site's* own
# address (해커스 → 서울 서초구, 다누리 → 서울 중구), which used to become the
# job's location.
FOOTER_MARKERS = re.compile(
    r"개인정보\s*처리\s*방침|개인정보\s*취급\s*방침|이용약관|저작권\s*정책|사업자\s*등록\s*번호|통신판매업|"
    r"copyright|all\s+rights\s+reserved|©|ⓒ",
    re.I,
)


def strip_site_chrome(text: str) -> str:
    """Cut the footer: from the first footer marker in the last 40% of the page."""
    tail_start = int(len(text) * 0.6)
    match = FOOTER_MARKERS.search(text, tail_start)
    return text[: match.start()] if match else text


def short_region(value: str) -> str | None:
    """Map "경기 수원시…", "서울특별시 …" or a bare "부산" to the short region name."""
    value = value.strip()
    head = re.match(rf"({REGION_NAMES})(?![가-힣])", value)
    if head:
        return head.group(1)
    for pattern, region in REGION_ALIASES:
        if re.match(pattern, value):
            return region
    return None


def extract_location(text: str) -> str | None:
    text = strip_site_chrome(text)
    # "근무\s*지역" must come before "근무지", or "근무지역 : 미국" leaves "역 : 미국".
    label = r"(?:근무\s*지역|근무\s*장소|근무지|소재지|지역)"
    labeled = re.search(label + r"\s*[:：]?\s*(.{2,80}?)(?=\s*(?:접수|마감일|지원\s*기간|기관|채용기관|채용상태|고용형태|$))", text)
    if labeled:
        value = clean_text(labeled.group(1))
        region = short_region(value)
        if region:
            return region
        first = value.split()[0] if value.split() else value
        if first in {"해외", "국외", "온라인", "재택"} or first in COUNTRY_NAMES:
            return first
    address = re.search(r"주소\s*[:：]?\s*(.{2,40})", text)
    if address:
        region = short_region(clean_text(address.group(1)))
        if region:
            return region
    for pattern, region in REGION_ALIASES:
        if re.search(pattern, text):
            return region
    # A bare region name only when it stands alone: "세종학당", "서울대학교" and
    # "해외여행에 결격사유가 없는 자" must not become locations.
    bare = re.search(rf"({REGION_NAMES})(?=$|[^가-힣]|시|도|캠퍼스|지역|소재)", text)
    return bare.group(1) if bare else None


def clean_extracted_field(value: str | None, fallback: str | None) -> str | None:
    if not value:
        return fallback
    cleaned = clean_text(value).replace("\\n", " ")
    # Notice numbers and years lead many titles: "(제2026-02-011호) 2026년 강북구가족센터".
    cleaned = re.sub(r"^\(?제?\s*[\d\-]+\s*호\)?\s*", "", cleaned)
    cleaned = re.sub(r"^20\d{2}\s*(?:학년도|년도|년)?\s*", "", cleaned)
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


def is_closed_url(conn: sqlite3.Connection, url: str) -> bool:
    return conn.execute("SELECT 1 FROM closed_urls WHERE url = ?", (url,)).fetchone() is not None


def mark_closed_url(conn: sqlite3.Connection, url: str, deadline: str | None) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO closed_urls (url, deadline, checked_at) VALUES (?, ?, ?)",
        (url, deadline, utc_now()),
    )


def job_exists_for_url(conn: sqlite3.Connection, url: str) -> bool:
    return conn.execute("SELECT 1 FROM jobs WHERE original_url = ? LIMIT 1", (url,)).fetchone() is not None


REVIEW_COLUMNS = {"status", "review_note", "reviewed_at"}


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
    if existing:
        job_id = int(existing[0])
        conn.execute(
            "DELETE FROM jobs WHERE job_id <> ? AND (content_hash = ? OR original_url = ?)",
            (job_id, job["content_hash"], job["original_url"]),
        )
        # A re-collected posting keeps the reviewer's decision and its first-seen date.
        columns = [column for column in job if column not in REVIEW_COLUMNS | {"first_seen_at"}]
        assignments = ", ".join(f"{column}=?" for column in columns)
        conn.execute(
            f"UPDATE jobs SET {assignments} WHERE job_id = ?",
            [job[column] for column in columns] + [job_id],
        )
        return "updated"

    job = {**job, "first_seen_at": job.get("first_seen_at") or job.get("collected_at") or utc_now()}
    columns = list(job.keys())
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO jobs ({', '.join(columns)}) VALUES ({placeholders})",
        [job[column] for column in columns],
    )
    return "saved"


UNIVERSITY_CORE = re.compile(r"([가-힣A-Za-z]{2,30}?(?:대학교|대학))")


def institution_core(institution: str | None, title: str) -> str | None:
    """The part of an institution name that stays the same across boards.

    "아주대학교 국제교육센터", "아주대학교" and a title "[아주대학교 국제교육센터] …"
    all reduce to "아주대학교", so one notice reposted on several boards groups.
    """
    for text in (institution or "", title):
        match = UNIVERSITY_CORE.search(text)
        if match:
            return normalize(match.group(1))
    return normalize(institution) if institution else None


def title_key(title: str | None) -> str:
    """A title reduced to what stays the same when another board reposts it.

    Drops new-post markers ("N", "New"), notice numbers, the board's own
    "접수중 2026.07.22~2026.07.29" tail and part suffixes ("-1", "(2)").
    """
    text = (title or "").strip()
    text = re.sub(r"^(?:N|New)\s+(?=\S)", "", text)
    text = re.sub(r"^\(?제?\s*[\d\-]+\s*호\)\s*", "", text)
    text = re.sub(r"\s*(?:접수중|접수\s*마감|마감|모집중)?\s*\d{4}\.\d{1,2}\.\d{1,2}\s*~\s*\d{4}\.\d{1,2}\.\d{1,2}\s*$", "", text)
    text = re.sub(r"\s*(?:-\s*\d|\(\d\))\s*$", "", text)
    # KLEOcean prefixes a category: "고려대학교 한국어 강사 채용 | [국제팀] …".
    text = re.sub(r"^[^|]{2,40}\s\|\s+(?=\S)", "", text)
    return normalize(text)


def assign_duplicate_groups(conn: sqlite3.Connection) -> int:
    """Group the same notice collected from different boards; mark one canonical.

    Two rows are the same notice when they share an institution core and a
    dated deadline, or when their titles reduce to the same key (a repost
    without a deadline, the same post reached through two board URLs). Rows
    are never deleted here: the public site shows only is_canonical = 1.
    Returns the number of non-canonical (duplicate) rows.
    """
    rows = conn.execute(
        "SELECT job_id, title, institution_name, deadline, content_hash, confidence_score, status, first_seen_at, source_name FROM jobs"
    ).fetchall()
    parent = {row[0]: row[0] for row in rows}

    def find(job_id: int) -> int:
        while parent[job_id] != job_id:
            parent[job_id] = parent[parent[job_id]]
            job_id = parent[job_id]
        return job_id

    first_by_title: dict[str, int] = {}
    # One institution can post two positions with one deadline on the same
    # board (세종대: 시간강사 / 강의전담강사), so institution + deadline only
    # joins rows that came from different boards: a repost.
    by_deadline: dict[str, list[tuple[int, str]]] = {}
    for job_id, title, institution, deadline, *_, source in rows:
        tkey = title_key(title)
        if len(tkey) >= 8:  # too short a title ("강사 모집") names no single notice
            if tkey in first_by_title:
                parent[find(job_id)] = find(first_by_title[tkey])
            else:
                first_by_title[tkey] = job_id
        core = institution_core(institution, title)
        if core and deadline and deadline != "rolling":
            seen = by_deadline.setdefault(f"{core}|{deadline}", [])
            for other_id, other_source in seen:
                if other_source != source:
                    parent[find(job_id)] = find(other_id)
                    break
            seen.append((job_id, source))

    groups: dict[int, list[tuple]] = {}
    for row in rows:
        groups.setdefault(find(row[0]), []).append(row)

    duplicates = 0
    for members in groups.values():
        key = hashlib.sha256(",".join(str(r[0]) for r in sorted(members)).encode("utf-8")).hexdigest()[:16] \
            if len(members) > 1 else members[0][4][:16]
        # Prefer a reviewed-approved row, then one that states its deadline,
        # then the most trusted board, then the oldest.
        members.sort(key=lambda r: (r[6] != "approved", not r[3], -(r[5] or 0), r[7] or "", r[0]))
        for index, row in enumerate(members):
            conn.execute(
                "UPDATE jobs SET duplicate_group_id = ?, is_canonical = ? WHERE job_id = ?",
                (key, 1 if index == 0 else 0, row[0]),
            )
            duplicates += index > 0
    return duplicates


# Boards that collect other institutions' notices. A link there shows the
# board's whole list, so a posting is better linked to its institution.
AGGREGATOR_HOSTS = {
    "klp.korean.go.kr": "국립국어원",
    "kteacher.korean.go.kr": "국립국어원",
    "www.iakle.com": "국제한국어교육학회",
    "iakle.com": "국제한국어교육학회",
    "kleocean.com": "한국어교육바다",
    "www.kleocean.com": "한국어교육바다",
    "korean.dsu.ac.kr": "동신대 한국어교원소식",
    "cess.dsu.ac.kr": "동신대 한국어교원소식",
    "kfl.snu.ac.kr": "서울대 한국어교육 공지",
    "nuri.iksi.or.kr": "누리 세종학당",
}
OFFICIAL_HOST = re.compile(r"\.(?:ac|go|or|re)\.kr$")
POST_PATH = re.compile(r"\d{3,}|view|artcl|board|bbs|notice|recruit", re.I)


def aggregator_name(url: str | None) -> str | None:
    return AGGREGATOR_HOSTS.get(urllib.parse.urlparse(url or "").hostname or "")


def url_in_body(text: str) -> str | None:
    """An institution post linked in an aggregator's copy of the notice."""
    for url in re.findall(r"https?://[^\s\"'<>()\[\]]+", text or ""):
        url = url.rstrip(".,;")
        parts = urllib.parse.urlparse(url)
        host = parts.hostname or ""
        if host in AGGREGATOR_HOSTS or host.endswith("korean.go.kr"):
            continue
        # A post, not a homepage: a homepage still shows nothing about the call.
        if parts.path.strip("/") and POST_PATH.search(parts.path + "?" + parts.query):
            return url
    return None


def naver_search(query: str, client_id: str, client_secret: str) -> list[dict]:
    request = urllib.request.Request(
        "https://openapi.naver.com/v1/search/webkr.json?" + urllib.parse.urlencode({"query": query, "display": 10}),
        headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8")).get("items", [])


def search_original(title: str, institution: str | None, client_id: str, client_secret: str) -> str | None:
    """The institution's own post, found by web search on its title.

    Accepted only on an official domain (.ac.kr, .go.kr, ...) that is not an
    aggregator, with a result title sharing most of our title's words.
    """
    words = [w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", title_key_text(title)) if w not in {"공고", "채용", "모집"}]
    if not words:
        return None
    query = f"{institution or ''} {' '.join(words[:6])}".strip()
    for item in naver_search(query, client_id, client_secret):
        link = item.get("link") or ""
        host = urllib.parse.urlparse(link).hostname or ""
        if host in AGGREGATOR_HOSTS or not OFFICIAL_HOST.search(host):
            continue
        found = re.sub(r"<[^>]+>", "", item.get("title") or "")
        shared = sum(1 for w in words if w in found)
        if shared >= max(2, (len(words) + 1) // 2):
            return link
    return None


def title_key_text(title: str) -> str:
    text = re.sub(r"^(?:N|New)\s+(?=\S)", "", (title or "").strip())
    return re.sub(r"^\[[^\]]{1,6}\]\s*", "", text)


def resolve_apply_urls(conn: sqlite3.Connection, naver: tuple[str, str] | None = None) -> dict[str, int]:
    """Pick, for every canonical posting, the most original link to apply through.

    original_url stays as collected; apply_url is what the site shows.
    Order: the collected link if it is not an aggregator; another board's
    copy of the same notice (duplicate group); a post URL in the body; a web
    search (only with Naver keys, once per posting); else the aggregator.
    """
    stats = {"original": 0, "group": 0, "body": 0, "search": 0, "aggregator": 0}
    rows = conn.execute(
        """
        SELECT job_id, original_url, duplicate_group_id, raw_text, title, institution_name, apply_url_source
        FROM jobs WHERE is_canonical = 1
        """
    ).fetchall()
    for job_id, original_url, group_id, raw_text, title, institution, previous in rows:
        url, how = original_url, "original"
        if aggregator_name(original_url):
            how = "aggregator"
            siblings = conn.execute(
                "SELECT original_url FROM jobs WHERE duplicate_group_id = ? AND job_id != ?", (group_id, job_id)
            ).fetchall()
            direct = [u for (u,) in siblings if not aggregator_name(u)]
            in_body = url_in_body(raw_text)
            if direct:
                url, how = direct[0], "group"
            elif in_body:
                url, how = in_body, "body"
            elif previous == "search":
                url, how = conn.execute("SELECT apply_url FROM jobs WHERE job_id = ?", (job_id,)).fetchone()[0], "search"
            elif naver and previous != "search_none":
                try:
                    found = search_original(title, institution, *naver)
                except Exception as exc:  # search is a bonus; never fail the run on it
                    print(f"naver search failed for job {job_id}: {exc}", file=sys.stderr)
                    found = None
                if found:
                    url, how = found, "search"
                else:
                    how = "search_none"
            elif previous == "search_none":
                how = "search_none"
        conn.execute("UPDATE jobs SET apply_url = ?, apply_url_source = ? WHERE job_id = ?", (url, how, job_id))
        stats["aggregator" if how == "search_none" else how] += 1
    return stats


def load_retired_source_names(path: Path) -> set[str]:
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {item["name"] for item in data.get("retired_sources", [])}


def purge_retired_sources(conn: sqlite3.Connection, names: set[str]) -> int:
    """Drop jobs collected from boards we no longer use (see retired_sources)."""
    if not names:
        return 0
    placeholders = ", ".join("?" for _ in names)
    cursor = conn.execute(f"DELETE FROM jobs WHERE source_name IN ({placeholders})", sorted(names))
    return cursor.rowcount


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
                terms=tuple(item.get("terms", ())),
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
        if job_exists_for_url(conn, source.url) or (active_only and is_closed_url(conn, source.url)):
            continue
        try:
            if source.body_hint is not None:
                # Boards that only answer POST were already read during discovery.
                html = ""
                text = source.body_hint
                files = list(source.attachments_hint)
            else:
                html = fetch_url(source.url)
                parsed_page = parse_html(html)
                text = parsed_page.text
                files = extract_attachments(parsed_page.links, source.url)
            title = source.title_hint or extract_html_title(html, text, source.url)
            stats["candidates"] += 1
            if has_excluded_term(title, exclude_terms):
                stats["skipped"] += 1
                continue
            if not is_relevant(f"{title} {text}", include_terms, hiring_terms, []):
                stats["skipped"] += 1
                continue

            deadline = source.deadline_hint or extract_deadline(text, today)
            posted_at = source.posted_at_hint or infer_posted_at(text, title, today)
            if active_only and not is_live_job(deadline, posted_at, None, today):
                mark_closed_url(conn, source.url, deadline)
                stats["skipped"] += 1
                continue
            # Never fall back to the source's own name: geocoding would then
            # place the job at the posting site's office.
            institution = (
                source.institution_hint
                or clean_extracted_field(extract_institution(text, title), None)
                or extract_bracketed_institution(title)
            )
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
                "posted_at": posted_at,
                "collected_at": utc_now(),
                "description": text[:4000],
                "raw_text": text[:20000],
                "attachments": attachments_json(files),
                "confidence_score": source.trust,
                "status": "needs_review",
                "content_hash": content_hash,
                "duplicate_group_id": content_hash[:16],
            }
            result = save_job(conn, job)
            stats[result] += 1
            conn.commit()
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
        print(f"source: {source.name}", file=sys.stderr, flush=True)
        try:
            if source.kind == "kteacher_list":
                discovered.extend(discover_kteacher(source, today, active_only))
            elif source.kind == "iakle_list":
                discovered.extend(
                    discover_iakle(source, include_terms, hiring_terms, today, active_only)
                )
            elif source.kind == "goe_recruit":
                discovered.extend(discover_goe_recruit(source))
            elif source.kind == "jinhakpro_sitemap":
                discovered.extend(
                    discover_jinhakpro_sitemap(conn, source, ["한국어", "Korean"], exclude_terms, today)
                )
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
        # Keep each board's work (closed_urls, discovery state) if a later one hangs.
        conn.commit()

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


ATTACHMENT_NAME = re.compile(r"\.(?:hwp|hwpx|pdf|docx?|xlsx?|zip)\s*$", re.I)


def extract_attachments(links: list[tuple[str, str]], base_url: str, limit: int = 6) -> list[tuple[str, str]]:
    """Notice files linked from a post: links whose text is a file name.

    Boards print the file name as the link text ("1. 채용공고문.pdf") whatever
    their download URL looks like, so the text is the reliable signal.
    """
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for text, href in links:
        name = clean_text(text)
        if not ATTACHMENT_NAME.search(name):
            continue
        url = urllib.parse.urljoin(base_url, href)
        if urllib.parse.urlparse(url).scheme not in {"http", "https"} or url in seen:
            continue
        seen.add(url)
        found.append((re.sub(r"^\d+\.\s*", "", name), url))
        if len(found) >= limit:
            break
    return found


def attachments_json(files: Iterable[tuple[str, str]]) -> str | None:
    files = list(files)
    return json.dumps([{"name": n, "url": u} for n, u in files], ensure_ascii=False) if files else None


MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


def fetch_file(url: str, timeout: int = 30) -> bytes:
    def once() -> bytes:
        safe_url = urllib.parse.quote(url, safe=":/?&=%#@")
        wait_for_host(safe_url)
        request = urllib.request.Request(safe_url, headers={"User-Agent": BROWSER_USER_AGENT})
        try:
            response = urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.URLError as exc:
            if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
                raise
            print(f"warning: TLS verification skipped for {safe_url}", file=sys.stderr)
            response = urllib.request.urlopen(request, timeout=timeout, context=ssl._create_unverified_context())
        with response:
            data = response.read(MAX_ATTACHMENT_BYTES + 1)
            kind = response.headers.get_content_type()
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise ValueError("attachment too large")
        # A login wall or error page answered instead of the file.
        if kind == "text/html" or data[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
            raise ValueError("got a web page, not a file")
        return data

    return with_deadline(once, (), timeout * 3)


def mirror_attachments(conn: sqlite3.Connection, files_dir: Path) -> dict[str, int]:
    """Download each published job's notice files into files_dir/<job_id>/.

    The site serves its own copies, so a reader never follows a link to the
    board that carried the post. The local name is recorded as "file" in the
    attachments JSON; a failed download is retried on the next run.
    """
    stats = {"mirrored": 0, "failed": 0}
    rows = conn.execute(
        "SELECT job_id, attachments FROM jobs WHERE status != 'rejected' AND is_canonical = 1 AND attachments IS NOT NULL"
    ).fetchall()
    for job_id, raw in rows:
        try:
            files = json.loads(raw)
        except ValueError:
            continue
        changed = False
        for index, item in enumerate(files, start=1):
            if item.get("file") and (files_dir / item["file"]).exists():
                continue
            suffix = Path(item.get("name") or "").suffix.lower()
            if not re.fullmatch(r"\.(?:hwp|hwpx|pdf|docx?|xlsx?|zip)", suffix):
                continue
            relative = f"{job_id}/{index}{suffix}"
            try:
                data = fetch_file(item["url"])
            except Exception as exc:  # network, size, login wall: try again next run
                print(f"attachment: job {job_id} {item.get('name')}: {exc}", file=sys.stderr)
                stats["failed"] += 1
                continue
            target = files_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            item["file"] = relative
            changed = True
            stats["mirrored"] += 1
        if changed:
            conn.execute("UPDATE jobs SET attachments = ? WHERE job_id = ?", (json.dumps(files, ensure_ascii=False), job_id))
            conn.commit()
    return stats


TEACHING_ROLE = re.compile(r"강사|교원|교사|교수|튜터|선생님|lecturer|instructor|teacher|tutor|faculty|professor", re.I)
ATTACHMENT_LINK = re.compile(r"fileDownload|download\.do|/download\b|\.(?:hwp|hwpx|pdf|docx?|xlsx?|zip)(?:$|[?#])", re.I)
POST_ID_PARAM = re.compile(r"(?:^|&)(?:uid|idx|seq|nttId|nttSn|articleNo|wr_id|bbs_idx|boardNo|no|id)=\d+", re.I)


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
        list_path = urllib.parse.urlparse(page_url).path
        for link_text, href in parsed.links:
            if not link_text:
                continue
            if urllib.parse.urlparse(href).scheme not in {"", "http", "https"}:
                continue
            absolute = urllib.parse.urljoin(page_url, href)
            # Links back to the board itself (filter tabs, paging) are navigation,
            # not postings, even when the query string looks relevant -- unless
            # the query names one post, as KBoard (?mod=document&uid=623) and
            # most Korean boards (?articleNo=…, ?nttId=…) do.
            parsed_link = urllib.parse.urlparse(absolute)
            if parsed_link.path == list_path and not POST_ID_PARAM.search(parsed_link.query):
                continue
            # Attachment links ("…공고.hwp") repeat the post title but are files.
            if ATTACHMENT_LINK.search(absolute):
                continue
            if not is_relevant(f"{link_text} {href}", include_terms, hiring_terms, []):
                continue
            # "모집" also matches student intakes and staff hiring; a posting
            # for us names a teaching role.
            if not TEACHING_ROLE.search(link_text):
                continue
            items.append(
                Source(
                    name=source.name,
                    url=absolute,
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


IAKLE_LIST_ENDPOINT = "/module/ntt/unity/selectNttListAjax.ink"
IAKLE_DETAIL_ENDPOINT = "/module/ntt/unity/selectNttDetailAjax.ink"
IAKLE_ROW = re.compile(r"<tr>(.*?)</tr>", re.DOTALL)
IAKLE_ROW_LINK = re.compile(r"fnView\('(\d+)'[^)]*\)[^>]*>(.*?)</a>", re.DOTALL)
IAKLE_ROW_DATE = re.compile(r"<td[^>]*>\s*(\d{4}\.\d{1,2}\.\d{1,2})\s*</td>")
IAKLE_HIDDEN_INPUT = re.compile(
    r'<input[^>]*id="(siteSeq|bbsSeq|menuSeq|sitecntntsSeq)"[^>]*value="(\d+)"'
)


def post_form(
    opener: urllib.request.OpenerDirector,
    url: str,
    fields: dict[str, str],
    referer: str,
    timeout: int = 25,
) -> str:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(fields).encode(),
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": referer,
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    return open_with_opener(opener, request, timeout)


IAKLE_BODY_MARKERS = (
    re.compile(r"첨부\s*파일\s*\(\d+\)"),
    re.compile(r"작성자\s*\S+"),
)
IAKLE_BODY_END = re.compile(r"조회수\s*[\d,]+")


def trim_iakle_body(text: str) -> str:
    """Drop the board's own chrome so only the notice itself is left.

    The detail fragment wraps the post in prev/next links and an author line;
    leaving them in makes extract_institution report the poster ("IAKLE") as the
    hiring institution.
    """
    # Both markers sit ahead of the post; start after whichever comes last.
    starts = [m.end() for m in (p.search(text) for p in IAKLE_BODY_MARKERS) if m]
    body = text[max(starts) :] if starts else text
    end = IAKLE_BODY_END.search(body)
    if end:
        body = body[: end.start()]
    return clean_text(body)


def discover_iakle(
    source: DiscoverySource,
    include_terms: list[str],
    hiring_terms: list[str],
    today: dt.date,
    active_only: bool,
) -> list[Source]:
    """Read the IAKLE notice board, which only answers POSTed AJAX calls.

    The board renders nothing on a plain GET and its rows carry no hrefs — each
    row is an fnView(nttSeq) call — so neither generic_links nor a seed URL can
    reach it. Post bodies are pasted out of HWP, and some carry only "see the
    attachment", so a post without a parseable deadline is left for the caller
    to drop.
    """
    parts = urllib.parse.urlsplit(source.url)
    origin = f"{parts.scheme}://{parts.netloc}"
    opener = build_session_opener()
    board_html = open_with_opener(opener, source.url, 25)
    fields = {name: value for name, value in IAKLE_HIDDEN_INPUT.findall(board_html)}
    if "bbsSeq" not in fields:
        raise ValueError(f"IAKLE board form not found at {source.url}")
    fields.update({"mngrAt": "N", "ordrSe": "D", "searchCnd": "frstRegistPnttm"})

    items: list[Source] = []
    seen_rows: set[str] | None = None
    for page in range(1, source.pages + 1):
        listing = post_form(
            opener, origin + IAKLE_LIST_ENDPOINT, {**fields, "pageIndex": str(page)}, source.url
        )
        rows = []
        for row_html in IAKLE_ROW.findall(listing):
            link = IAKLE_ROW_LINK.search(row_html)
            if not link:
                continue
            posted = IAKLE_ROW_DATE.search(row_html)
            rows.append((link.group(1), link.group(2), normalize_date(posted.group(1)) if posted else None))
        if not rows:
            break
        page_rows = {seq for seq, _, _ in rows}
        if seen_rows is not None and page_rows == seen_rows:
            break
        seen_rows = page_rows

        for ntt_seq, raw_title, posted_at in rows:
            title = html_clean(raw_title)
            if not is_relevant(title, include_terms, hiring_terms, []):
                continue
            detail = post_form(
                opener,
                origin + IAKLE_DETAIL_ENDPOINT,
                {**fields, "pageIndex": str(page), "nttSeq": ntt_seq, "parntsNttSeq": "", "secretAt": ""},
                source.url,
            )
            detail_page = parse_html(detail)
            text = trim_iakle_body(detail_page.text)
            deadline = extract_deadline(text)
            if active_only and not is_active_deadline(deadline, today):
                continue
            items.append(
                Source(
                    name=source.name,
                    url=f"{source.url}?nttSeq={ntt_seq}",
                    trust=source.trust,
                    kind="discovered_iakle",
                    title_hint=title,
                    institution_hint=clean_extracted_field(extract_institution(text, title), None),
                    deadline_hint=deadline,
                    posted_at_hint=posted_at,
                    body_hint=text,
                    # IAKLE posts are often just "see the attached notice".
                    attachments_hint=tuple(extract_attachments(detail_page.links, origin + "/")),
                )
            )
    return items


JINHAKPRO_SITEMAP_ID = re.compile(r"/recruit/(\d+)\s*</loc>")


def discover_jinhakpro_sitemap(
    conn: sqlite3.Connection,
    source: DiscoverySource,
    include_terms: list[str],
    exclude_terms: list[str],
    today: dt.date,
) -> list[Source]:
    """진학프로 via its published sitemap.

    Universities post their own calls here to take applications, so this is
    the institutions' channel, not a repost (robots.txt allows /recruit/). The
    list page only shows 24 posts and ignores paging; the sitemap lists them
    all. Posts are opened newest first, at most source.pages per run; a post
    that is not a Korean-teaching call is remembered in closed_urls so it is
    opened once. Relevance is judged on the post's own title: its pages carry
    a sidebar of other calls that mention 한국어.
    """
    sitemap = fetch_url(source.url)
    ids = sorted({int(i) for i in JINHAKPRO_SITEMAP_ID.findall(sitemap)}, reverse=True)
    items: list[Source] = []
    opened = 0
    for post_id in ids:
        if opened >= source.pages:
            break
        url = f"https://www.jinhakpro.com/recruit/{post_id}"
        if job_exists_for_url(conn, url) or is_closed_url(conn, url):
            continue
        opened += 1
        try:
            text = parse_html(fetch_url(url)).text
        except HostRateLimited:
            break  # the rest waits for the next run
        except Exception:
            continue  # tried again next run
        institution, title = extract_jinhakpro_heading(text)
        title = title or ""
        relevant = (
            any(term.casefold() in title.casefold() for term in include_terms)
            and TEACHING_ROLE.search(title)
            and not has_excluded_term(title, exclude_terms)
        )
        deadline = extract_deadline(text, today)
        if not relevant or not is_live_job(deadline, None, None, today):
            mark_closed_url(conn, url, deadline)
            continue
        items.append(
            Source(
                name=source.name,
                url=url,
                trust=source.trust,
                kind="discovered_jinhakpro",
                title_hint=title,
                institution_hint=institution,
                location_hint=extract_jinhakpro_location(text),
                deadline_hint=deadline,
                body_hint=text,
            )
        )
    return items


GOE_ROW = re.compile(r"goView\('(\d+)'\)(.*?)</li>", re.DOTALL)


def discover_goe_recruit(source: DiscoverySource) -> list[Source]:
    """경기도교육청 구인구직: the list only answers a POSTed title search.

    The page renders no rows on a plain GET; its search form posts back to the
    same URL. Each term in source.terms is searched separately (한국어 classes
    for immigrant pupils are often titled 다문화 or 한국어학급 only). Detail
    pages answer a plain GET.
    """
    origin = "https://www.goe.go.kr"
    opener = build_session_opener()
    open_with_opener(opener, source.url, 25)  # session cookie for the search
    items: list[Source] = []
    seen: set[str] = set()
    for term in source.terms or ("한국어",):
        form = {
            "mi": "10502", "currPage": "1", "srchEcptDl": "Y", "pageIndex": "40",
            "searchType": "sj", "searchValue": term, "srchOcptCd": "", "srchOcptNm": "",
        }
        request = urllib.request.Request(
            origin + "/recruit/ad/func/pb/hnfpPbancList.do",
            data=urllib.parse.urlencode(form).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": source.url},
        )
        listing = open_with_opener(opener, request, 25)
        for post_id, row in GOE_ROW.findall(listing):
            if post_id in seen:
                continue
            seen.add(post_id)
            title = re.search(r'class="cont_tit">(.*?)</p>', row, re.DOTALL)
            school = re.search(r'class="cont_top">\s*<span>(.*?)</span>', row, re.DOTALL)
            title_text = html_clean(title.group(1)) if title else ""
            title_text = re.sub(r"^(?:마감임박|오늘마감|신규)\s*", "", title_text)
            items.append(
                Source(
                    name=source.name,
                    url=f"{origin}/recruit/ad/func/pb/hnfpPbancInfoView.do?mi=10502&pbancSn={post_id}",
                    trust=source.trust,
                    kind="discovered_goe",
                    title_hint=title_text or None,
                    institution_hint=html_clean(school.group(1)) if school else None,
                    location_hint="경기",
                )
            )
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
                    url=urllib.parse.urljoin(page_url, row["path"]),
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
        # The board moved from kteacher.korean.go.kr/jobsearch/… to klp.korean.go.kr/certif/jobsearch/….
        link = re.search(r'href="((?:/certif)?/jobsearch/(\d+))"[^>]*>(.*?)</a>', cells[2], flags=re.DOTALL)
        if not link:
            continue
        rows.append(
            {
                "path": link.group(1),
                "id": link.group(2),
                "group": html_clean(cells[1]),
                "title": html_clean(link.group(3)),
                "institution": html_clean(cells[3]),
                "deadline": parse_kteacher_deadline(html_clean(cells[5])),
            }
        )
    return rows


def parse_kteacher_deadline(value: str) -> str | None:
    # Open-ended posts print "상시모집" instead of a date; one such row used to
    # abort the whole kteacher listing.
    if re.search(r"\d{4}[.\-/]?\d{1,2}[.\-/]?\d{1,2}", value):
        return normalize_date(value)
    if "상시" in value or "채용시" in value:
        return "rolling"
    return None


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


# Board tags in brackets that name a post type, not the hiring institution.
BRACKET_TAGS = {"공고", "홍보", "채용", "모집", "안내", "재공고", "추가", "긴급", "공지", "알림", "마감임박"}


def extract_bracketed_institution(title: str) -> str | None:
    for match in re.finditer(r"\[([^\]]+)\]", title):
        value = clean_text(match.group(1))
        if value not in BRACKET_TAGS:
            return value
    return None


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
    # A status tag may lead the page title: "연장 - 숙명여자대학교 …" for an extended call.
    text = re.sub(r"^\s*(?:연장|마감|접수중|진행중|재공고)\s*-\s*", "", text)
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


# 지역명만 담긴 location_text는 기관 검색이 실패했을 때만 쓰는 대략적인 보조 좌표다.
REGION_FALLBACK_QUERY = {
    "서울": "서울특별시청", "부산": "부산광역시청", "대구": "대구광역시청",
    "인천": "인천광역시청", "광주": "광주광역시청", "대전": "대전광역시청",
    "울산": "울산광역시청", "세종": "세종특별자치시청", "경기": "경기도청",
    "강원": "강원특별자치도청", "충북": "충청북도청", "충남": "충청남도청",
    "전북": "전북특별자치도청", "전남": "전라남도청", "경북": "경상북도청",
    "경남": "경상남도청", "제주": "제주특별자치도청", "창원": "창원시청",
}


GENERIC_INSTITUTION_NAMES = {
    "가족센터", "다문화가족지원센터", "건강가정지원센터", "한국어학당", "어학당", "언어교육원",
    "국제교육원", "한국어교육원", "한국어교육센터", "교육센터", "센터", "교육원", "세종학당", "학원",
}


def kakao_local_search(url: str, query: str, rest_key: str) -> dict | None:
    request = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode({'query': query, 'size': 1})}",
        headers={"Authorization": f"KakaoAK {rest_key}"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    documents = payload.get("documents") or []
    if not documents:
        return None
    top = documents[0]
    try:
        latitude = float(top["y"])
        longitude = float(top["x"])
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "latitude": latitude,
        "longitude": longitude,
        "address": top.get("road_address_name") or top.get("address_name"),
        "place_name": top.get("place_name") or top.get("address_name"),
    }


def geocode_query(conn: sqlite3.Connection, query: str, rest_key: str) -> dict | None:
    """Resolve one place name to coordinates, caching every answer.

    Misses are cached too (as NULL coordinates) so a name Kakao cannot find is
    not retried on every run.
    """
    cached = conn.execute(
        "SELECT latitude, longitude, address, place_name FROM geocode_cache WHERE query = ?",
        (query,),
    ).fetchone()
    if cached is not None:
        if cached[0] is None:
            return None
        return {"latitude": cached[0], "longitude": cached[1], "address": cached[2], "place_name": cached[3]}

    result = None
    for url in (KAKAO_KEYWORD_URL, KAKAO_ADDRESS_URL):
        try:
            result = kakao_local_search(url, query, rest_key)
        except Exception as exc:
            print(f"kakao geocode failed for {query!r}: {exc}", file=sys.stderr)
            return None
        if result:
            break

    conn.execute(
        """
        INSERT OR REPLACE INTO geocode_cache
            (query, latitude, longitude, address, place_name, looked_up_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            query,
            result["latitude"] if result else None,
            result["longitude"] if result else None,
            result["address"] if result else None,
            result["place_name"] if result else None,
            utc_now(),
        ),
    )
    return result


def geocode_jobs(conn: sqlite3.Connection) -> dict[str, int]:
    """Fill in coordinates for saved jobs that do not have them yet.

    Searches on the institution name, which is the most specific place name the
    collector has; location_text only names a province and often reflects the
    posting site's own office rather than the workplace, so it is a last resort.
    """
    stats = {"geocoded": 0, "unresolved": 0}
    rest_key = os.environ.get("KAKAO_REST_API_KEY")
    if not rest_key:
        return stats

    rows = conn.execute(
        """
        SELECT job_id, institution_name, location_text
        FROM jobs
        WHERE latitude IS NULL AND status != 'rejected'
          AND COALESCE(is_overseas, 0) = 0
          AND COALESCE(institution_type, '') != 'online'
        """
    ).fetchall()
    for job_id, institution, location in rows:
        if location in {"해외", "국외", "온라인", "재택"} or location in COUNTRY_NAMES:
            continue
        result = None
        by_institution = False
        # A bare unit name ("가족센터") matches some other branch anywhere in the country.
        if institution and clean_text(institution) in GENERIC_INSTITUTION_NAMES:
            institution = None
        for query in (institution, REGION_FALLBACK_QUERY.get(clean_text(location or ""))):
            if not query:
                continue
            result = geocode_query(conn, query, rest_key)
            if result:
                by_institution = query == institution
                break
        if not result:
            stats["unresolved"] += 1
            continue
        # The institution's real address beats the region guessed from page text.
        region = short_region(result["address"] or "") if by_institution else None
        conn.execute(
            """
            UPDATE jobs
            SET latitude = ?, longitude = ?, address = ?, place_name = ?,
                location_text = COALESCE(?, location_text)
            WHERE job_id = ?
            """,
            (result["latitude"], result["longitude"], result["address"], result["place_name"], region, job_id),
        )
        stats["geocoded"] += 1
    conn.commit()
    return stats


def fill_job_fields(conn: sqlite3.Connection, llm_backend: str | None, llm_limit: int) -> dict[str, int]:
    """Fill the structured columns (JOB_FIELD_COLUMNS) for jobs that lack them.

    Rules run for every job not yet extracted. With an llm_backend, jobs whose
    fields so far came only from rules also go to Claude, at most llm_limit per
    run, so each posting is sent once and the usage per run stays bounded.
    """
    stats = {"rules": 0, "llm": 0, "llm_failed": 0}
    conn.row_factory = sqlite3.Row
    try:
        pending = conn.execute(
            """
            SELECT job_id, title, institution_name, location_text, deadline, description, raw_text, fields_source
            FROM jobs
            WHERE status != 'rejected' AND is_canonical = 1
              AND (fields_source IS NULL OR fields_source = 'rules' OR body_text IS NULL)
            -- Public (domestic, online) postings go to Claude first; overseas
            -- ones are only shown in the private build.
            ORDER BY COALESCE(is_overseas, 0), job_id
            """
        ).fetchall()
    finally:
        conn.row_factory = None

    extractor = extract_fields.make_extractor(llm_backend) if llm_backend else None
    for row in pending:
        job = dict(row)
        fields = None
        source = "rules"
        if extractor is not None and stats["llm"] + stats["llm_failed"] < llm_limit:
            text = strip_site_chrome(job["raw_text"] or job["description"] or "")
            try:
                fields = extractor(job, text)
            except extract_fields.LlmUnavailable as exc:
                print(f"llm fields stopped: {exc}", file=sys.stderr)
                extractor = None
            if fields is not None:
                source = "llm"
                stats["llm"] += 1
                print(f"llm fields: job {job['job_id']} done", file=sys.stderr)
            elif extractor is not None:
                stats["llm_failed"] += 1
        if fields is None:
            # Never replace Claude's fields with rules; the body comes next run.
            if job["fields_source"] in {"rules", "llm"}:
                continue
            fields = extract_fields.extract_rules(job)
            stats["rules"] += 1
        columns = [column for column, _ in JOB_FIELD_COLUMNS if column in fields]
        assignments = ", ".join(f"{column} = ?" for column in columns)
        conn.execute(
            f"UPDATE jobs SET {assignments}, fields_source = ?, fields_extracted_at = ? WHERE job_id = ?",
            [fields[column] for column in columns] + [source, utc_now(), job["job_id"]],
        )
    return stats


def collect(args: argparse.Namespace) -> int:
    load_secrets_file(Path(args.secrets))
    keywords, include_terms, hiring_terms, exclude_terms, sources = load_config(Path(args.sources))
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    if args.sample:
        sample_url = SAMPLE_HTML.as_uri()
        sources = [Source("local sample", sample_url, 100, "sample")]

    conn = init_db(Path(args.db))
    retired_names = load_retired_source_names(Path(args.discovery_file))
    if args.jinhakpro_pages > 0:
        retired_names.discard("진학프로 강사 목록")  # explicitly re-enabled for this run
    retired = purge_retired_sources(conn, retired_names)
    if retired:
        print(f"removed {retired} jobs from retired sources")
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
        if args.active_only and not args.sample:
            # Refresh may have pushed deadlines into the past; never leave
            # closed postings in the DB until the next run.
            prune_inactive_jobs(conn, today)
        finish_run(conn, run_id, stats)
        conn.commit()
        fields = fill_job_fields(conn, args.llm_backend if args.llm_fields else None, args.llm_limit)
        duplicates = assign_duplicate_groups(conn)
        naver_keys = (os.environ.get("NAVER_CLIENT_ID"), os.environ.get("NAVER_CLIENT_SECRET"))
        links = resolve_apply_urls(conn, naver_keys if all(naver_keys) else None)
        conn.commit()
        print(
            f"fields: rules={fields['rules']} llm={fields['llm']} llm_failed={fields['llm_failed']} "
            f"duplicates={duplicates}"
        )
        print("apply links: " + " ".join(f"{k}={v}" for k, v in links.items()))
        mirrored = mirror_attachments(conn, Path(args.files_dir))
        print(f"attachments: mirrored={mirrored['mirrored']} failed={mirrored['failed']}")
        if args.geocode:
            geo = geocode_jobs(conn)
            if geo["geocoded"] or geo["unresolved"]:
                print(f"geocoded={geo['geocoded']} ungeocoded={geo['unresolved']}")
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
    parser.add_argument("--files-dir", default=str(DEFAULT_FILES_DIR), help="Where notice attachments are mirrored")
    parser.add_argument("--url-file", default=str(DEFAULT_URL_FILE), help="CSV seed URL file")
    parser.add_argument(
        "--discovery-file",
        default=str(DEFAULT_DISCOVERY_FILE),
        help="Discovery source config JSON path (auto list/id-range crawlers)",
    )
    parser.add_argument("--sample", action="store_true", help="Use local sample_jobs.html")
    parser.add_argument("--nuri-pages", type=int, default=126, help="Nuri KSI list pages to collect")
    parser.add_argument(
        "--jinhakpro-pages",
        type=int,
        default=0,
        help="JinhakPro lecturer list pages to collect (off by default: it re-posts other boards' notices)",
    )
    parser.add_argument(
        "--llm-fields",
        action="store_true",
        help="Send postings without LLM fields to Claude for structured fields and a summary",
    )
    parser.add_argument(
        "--llm-backend",
        choices=["claude-code", "api"],
        default="claude-code",
        help="claude-code: the local `claude` CLI on the signed-in account (default); api: ANTHROPIC_API_KEY",
    )
    parser.add_argument("--llm-limit", type=int, default=50, help="Max postings sent to Claude per run")
    parser.add_argument("--today", default=None, help="Active-period reference date, YYYY-MM-DD")
    parser.add_argument("--include-expired", dest="active_only", action="store_false", help="Keep expired or undated jobs")
    parser.add_argument(
        "--no-refresh",
        dest="refresh",
        action="store_false",
        help="Skip re-fetching already-saved jobs' own URLs to catch deadline changes",
    )
    parser.add_argument(
        "--no-geocode",
        dest="geocode",
        action="store_false",
        help="Skip Kakao lookups that place saved jobs on the map",
    )
    parser.set_defaults(active_only=True, refresh=True, geocode=True)
    parser.add_argument("--saramin-count", type=int, default=50, help="Saramin jobs per keyword")
    parser.add_argument(
        "--secrets",
        default=str(DEFAULT_SECRETS_FILE),
        help="Gitignored KEY=value file holding site credentials",
    )
    return parser


if __name__ == "__main__":
    sys.exit(collect(build_parser().parse_args()))
