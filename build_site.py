#!/usr/bin/env python3
"""Build the public job board as static HTML from the collector's SQLite DB.

    python build_site.py                      # writes site/
    python -m http.server -d site 8000        # preview at http://localhost:8000

Every value from a collected posting is untrusted text from another site: it is
HTML-escaped on the way out, and only http(s) links are ever linked.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import datetime as dt
import html
import json
import math
import os
import re
import shutil
import sqlite3
import sys
import urllib.parse
from pathlib import Path

import collect_jobs
import review_items

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "site_static"
DEFAULT_OUT = ROOT / "site"
# Owner-only build that also shows overseas jobs. Gitignored; never deploy it.
PRIVATE_OUT = ROOT / "site_private"
# Admin-only staging (/test on the live server, see serve.py): changes are
# tried here before they reach the public site.
TEST_STATIC_DIR = ROOT / "site_test_static"
TEST_OUT = ROOT / "site_test"
KST = dt.timezone(dt.timedelta(hours=9))

SITE_NAME = "한국어강사 채용판"
FONT_CSS = "https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css"
# Fill in once the services exist; a None link hides that block.
SERVICE_LINKS = {"mentoring": None, "ebook": None}

INSTITUTION_TYPE_LABELS = {
    "university": "국내 대학",
    "overseas_university": "해외 대학",
    "sejong": "세종학당",
    "multicultural": "가족센터·다문화",
    "kiip": "사회통합프로그램",
    "school": "초중고·교육청",
    "academy": "학원",
    "online": "온라인",
    "government": "공공기관",
}
WEEKDAYS = "월화수목금토일"


def e(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def safe_url(url: str | None) -> str | None:
    """Only http(s) links leave the builder; anything else (javascript:, data:) is dropped."""
    if not url:
        return None
    return url if urllib.parse.urlparse(url).scheme in {"http", "https"} else None


def json_for_script(data: object) -> str:
    """JSON that is safe inside a <script> element."""
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


# --- data --------------------------------------------------------------------

def load_jobs(conn: sqlite3.Connection, today: dt.date, approved_only: bool, include_overseas: bool = False) -> list[dict]:
    conn.row_factory = sqlite3.Row
    statuses = ("approved",) if approved_only else ("approved", "needs_review")
    rows = conn.execute(
        f"""
        SELECT * FROM jobs
        WHERE is_canonical = 1 AND status IN ({", ".join("?" for _ in statuses)})
        """,
        statuses,
    ).fetchall()
    conn.row_factory = None
    jobs = [
        prepare(dict(row), today)
        for row in rows
        if collect_jobs.is_live_job(row["deadline"], row["posted_at"], row["first_seen_at"], today)
    ]
    # Overseas postings are still collected but only shown in the private build.
    if not include_overseas:
        jobs = [job for job in jobs if job["scope"] != "overseas"]
    # Dated deadlines first (soonest on top), then rolling, then unknown.
    jobs.sort(key=lambda j: (j["sort_days"], j["job_id"]))
    return jobs


def job_scope(job: dict) -> str:
    if job.get("institution_type") == "online" or job.get("location_text") in {"온라인", "재택"}:
        return "online"
    if job.get("is_overseas"):
        return "overseas"
    return "domestic"


def days_until(deadline: str | None, today: dt.date) -> int | None:
    if not deadline or deadline == "rolling":
        return None
    try:
        return (dt.date.fromisoformat(deadline) - today).days
    except ValueError:
        return None


def deadline_badge(deadline: str | None, today: dt.date) -> tuple[str, str]:
    """(label, css class). Mirrors badgeFor() in site_static/app.js."""
    if deadline == "rolling":
        return "상시 모집", "rolling"
    days = days_until(deadline, today)
    if days is None:
        return "마감일 미정", ""
    if days == 0:
        return "오늘 마감", "urgent"
    if days <= 7:
        return f"마감 D-{days}", "urgent"
    return f"D-{days}", ""


def deadline_text(deadline: str | None) -> str:
    if deadline == "rolling":
        return "채용될 때까지"
    if not deadline:
        return "공고 내용을 확인해 주세요"
    try:
        day = dt.date.fromisoformat(deadline)
    except ValueError:
        return deadline
    return f"{day.year}년 {day.month}월 {day.day}일 ({WEEKDAYS[day.weekday()]})"


def place_text(job: dict) -> str:
    if job["scope"] == "online":
        return "온라인·재택"
    if job["scope"] == "overseas":
        country = job.get("country") or job.get("location_text")
        return country if country and country not in {"해외", "국외"} else "국가 미정"
    if job.get("address"):
        return " ".join(job["address"].split()[:2])
    return job.get("location_text") or "지역 미확인"


def display_title(title: str | None) -> str:
    """Drop board clutter: KLEOcean's "N" new-post marker, notice numbers like "(제2026-02-011호)"."""
    text = (title or "").strip()
    text = re.sub(r"^(?:N|New)\s+(?=\S)", "", text)
    text = re.sub(r"^\(?제?\s*[\d\-]+\s*호\)\s*", "", text)
    # KBoard list titles end with the board's own status: "… 접수중 2026.07.22~2026.07.29".
    text = re.sub(r"\s+(?:접수중|접수\s*마감|마감|모집중)?\s*\d{4}\.\d{1,2}\.\d{1,2}\s*~\s*\d{4}\.\d{1,2}\.\d{1,2}\s*$", "", text)
    return text or "제목 미확인"


def prepare(job: dict, today: dt.date) -> dict:
    job["title"] = display_title(job.get("title"))
    job["scope"] = job_scope(job)
    days = days_until(job.get("deadline"), today)
    job["sort_days"] = days if days is not None else (10_000 if job.get("deadline") == "rolling" else 20_000)
    job["badge"], job["badge_class"] = deadline_badge(job.get("deadline"), today)
    job["place"] = place_text(job)
    job["org"] = job.get("institution_name") or "기관 미확인"
    job["path"] = f"jobs/{job['job_id']}.html"
    email = job.get("apply_email") or ""
    job["apply_email"] = email if re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", email) else None
    try:
        files = json.loads(job.get("attachments") or "[]")
    except ValueError:
        files = []
    # Only the copies the collector mirrored (mirror_attachments): the page
    # never links to the board that carried the post.
    job["summary"] = public_text(job.get("summary"))
    job["files"] = [
        (public_file_name(f.get("name") or "첨부파일", f["file"]), f["file"]) for f in files
        if isinstance(f.get("file"), str) and re.fullmatch(r"\d+/\d+\.[a-z]{2,4}", f["file"])
    ]
    job["has_place"] = job["scope"] == "domestic" and job.get("latitude") is not None and job.get("longitude") is not None
    chips = [INSTITUTION_TYPE_LABELS.get(job.get("institution_type") or "")]
    chips += [
        short(job.get("qualification"), 16),
        "신입 가능" if job.get("newcomer_ok") == 1 else None,
        "모의수업 있음" if job.get("demo_lesson") == 1 else None,
        short(job.get("salary_text"), 18),
    ]
    job["chips"] = [c for c in chips if c][:4]
    return job


# Boards that carry copies of notices. Their names and addresses never reach a
# page, even when Claude leaves one in body_text.
BOARD_HOSTS = set(collect_jobs.AGGREGATOR_HOSTS) | {"www.jinhakpro.com", "jinhakpro.com", "www.hibrain.net", "hibrain.net"}
BOARD_NAMES = re.compile(
    "|".join(map(re.escape, sorted(set(collect_jobs.AGGREGATOR_HOSTS.values()) | {
        "한국어교원 구인정보", "한국어교원 자격", "국제한국어교육학회", "한국어교육바다", "진학프로", "하이브레인넷", "누리-세종학당",
    }, key=len, reverse=True)))
)
URL_IN_TEXT = re.compile(r"https?://[^\s<>\"')\]]+")
EMAIL_IN_TEXT = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


SOURCE_HINT = re.compile(r"원문|출처")
# Lines a board adds to every copy, which give away that the page is a copy.
BOARD_BOILERPLATE = re.compile(r"원문|출처|해당\s*기관의?\s*(?:채용\s*)?공고를?\s*(?:반드시\s*)?확인")


def public_text(text: str | None) -> str | None:
    """Drop the sentences of a summary that name a board or point to an original post."""
    if not text:
        return text
    sentences = re.split(r"(?<=[.!?。])\s+|(?<=다\.)\s*", text)
    kept = [s for s in sentences if s.strip() and not BOARD_NAMES.search(s) and not SOURCE_HINT.search(s)]
    return " ".join(kept) or None


def public_file_name(name: str, path: str) -> str:
    """A file's download name without a board's name in it."""
    cleaned = re.sub(r"^[\s_\-()\[\]·.,]+", "", BOARD_NAMES.sub("", name))
    cleaned = re.sub(r"^구인정보[\s_\-()]*", "", cleaned)
    if ")" in cleaned and cleaned.index(")") < (cleaned.index("(") if "(" in cleaned else len(cleaned)):
        cleaned = cleaned.replace(")", " ", 1).replace("  ", " ")
    return cleaned if Path(cleaned).stem.strip(" _-()") else "공고문" + Path(path).suffix


def inline_html(line: str) -> str:
    """Escape a line; link emails and the hiring side's own links, drop board links."""
    parts, last = [], 0
    for match in re.finditer(f"{URL_IN_TEXT.pattern}|{EMAIL_IN_TEXT.pattern}", line):
        parts.append(e(line[last:match.start()]))
        token = match.group(0)
        if token.startswith("http"):
            host = (urllib.parse.urlparse(token).hostname or "").lower()
            if host not in BOARD_HOSTS and safe_url(token):
                parts.append(f'<a href="{e(token)}" target="_blank" rel="noopener nofollow">{e(token)}</a>')
        else:
            parts.append(f'<a href="mailto:{e(token)}">{e(token)}</a>')
        last = match.end()
    parts.append(e(line[last:]))
    return "".join(parts)


def notice_html(text: str | None) -> str:
    """Render body_text ("## " headings, "- " items, blank-line paragraphs) as HTML."""
    if not text or not text.strip():
        return ""
    out: list[str] = []
    para: list[str] = []
    items: list[str] = []

    def flush() -> None:
        if para:
            out.append("<p>" + "<br>".join(para) + "</p>")
            para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>")
            items.clear()

    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if BOARD_NAMES.search(line) or BOARD_BOILERPLATE.search(line):
            continue
        if not line:
            flush()
        elif line.startswith("#"):
            flush()
            out.append(f"<h3>{inline_html(line.lstrip('#').strip())}</h3>")
        elif re.match(r"^[-•·*]\s+", line):
            if para:
                flush()
            items.append(inline_html(re.sub(r"^[-•·*]\s+", "", line)))
        else:
            if items:
                flush()
            para.append(inline_html(line))
    flush()
    return "\n".join(out)


# --- how to apply -----------------------------------------------------------------

APPLY_EMAIL_WORDS = re.compile(r"이메일|e-?mail|메일", re.I)
APPLY_ONLINE_WORDS = re.compile(r"온라인|홈페이지|폼|form|사이트|시스템|회원\s*가입|웹", re.I)
APPLY_POST_WORDS = re.compile(r"우편|등기|택배")
APPLY_VISIT_WORDS = re.compile(r"방문")
# Hosts that are application systems themselves: a university posts there to
# receive applications, so the applicant has to go there.
APPLY_SYSTEM_HOSTS = {"www.jinhakpro.com", "jinhakpro.com"}
PHONE = re.compile(r"0\d{1,2}[-)\s.]?\d{3,4}[-\s.]?\d{4}")


def apply_text(job: dict) -> str:
    """What the posting says about applying: how_to_apply plus the body's 접수 lines."""
    lines = [job.get("how_to_apply") or ""]
    lines += [l for l in (job.get("body_text") or "").splitlines() if re.search(r"접수|지원\s*방법|제출\s*방법", l)]
    return "\n".join(lines)


def apply_links(job: dict) -> list[tuple[str, str]]:
    """(label, url) for pages where one actually applies; never a board that only carries the notice."""
    found: list[tuple[str, str]] = []
    for url in URL_IN_TEXT.findall(job.get("body_text") or ""):
        url = url.rstrip(".,;")
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        if host in BOARD_HOSTS or not safe_url(url) or any(u == url for _, u in found):
            continue
        if host in {"forms.gle", "docs.google.com"}:
            label = "구글 폼 지원서"
        elif host in {"form.naver.com", "m.site.naver.com", "naver.me"}:
            label = "네이버 폼 지원서"
        else:
            label = f"{host.removeprefix('www.')} 지원 페이지"
        found.append((label, url))
    original = safe_url(job.get("original_url"))
    # The application system's page only when the notice gives no form of its own.
    if not found and original and (urllib.parse.urlparse(original).hostname or "").lower() in APPLY_SYSTEM_HOSTS:
        found.append(("온라인 접수 페이지", original))
    return found


def apply_guide(job: dict) -> str:
    """The 지원하기 cards, one per way the posting accepts applications."""
    text = apply_text(job)
    email = job["apply_email"]
    links = apply_links(job)
    system_link = [l for l in links if (urllib.parse.urlparse(l[1]).hostname or "") in APPLY_SYSTEM_HOSTS]
    online = bool(APPLY_ONLINE_WORDS.search(text)) or (bool(links) and not email)
    # "이메일지원" on an application system means its own e-mail form, not an address.
    if not email and APPLY_EMAIL_WORDS.search(text) and system_link:
        online = True
    # "방문 및 우편접수 불가" rules them out rather than in.
    allowed = "\n".join(l for l in text.splitlines() if not re.search(r"불가|받지\s*않|안\s*됨|제외", l))
    post = bool(APPLY_POST_WORDS.search(allowed))
    visit = bool(APPLY_VISIT_WORDS.search(allowed))
    how = job.get("how_to_apply")
    cards: list[str] = []

    if email:
        cards.append(f"""<div class="apply-card apply-email">
<p class="label">이메일로 지원해요</p>
<div class="addr-row"><strong class="addr" data-copy-text>{e(email)}</strong>
<button type="button" class="btn btn-primary" data-copy>이메일 주소 복사하기</button>
<span data-copy-status role="status"></span></div>
<p class="tip">메일 제목에 지원 분야와 이름을 적고, 제출 서류를 빠짐없이 첨부하세요.</p></div>""")
    if online and links:
        buttons = "".join(
            f'<a class="btn btn-primary" href="{e(url)}" target="_blank" rel="noopener nofollow">{e(label)} 열기</a>'
            for label, url in links
        )
        note = f'<p class="tip">{e(how)}</p>' if how and not email else ""
        if system_link and not email and APPLY_EMAIL_WORDS.search(text):
            note = '<p class="tip">접수 페이지에서 <strong>이메일 지원</strong>을 눌러 서류를 보내요.</p>'
        cards.append(f"""<div class="apply-card"><p class="label">온라인으로 지원해요</p>
<div class="btn-row">{buttons}</div>{note}</div>""")
    elif online and not email:
        cards.append(f"""<div class="apply-card"><p class="label">온라인으로 지원해요</p>
<p class="tip">{e(how or "기관 홈페이지의 온라인 접수로 지원해요.")} 지원 주소는 아래 공고문에서 확인하세요.</p></div>""")
    if post or visit:
        ways = " 또는 ".join(w for w, on in (("우편", post), ("방문", visit)) if on)
        where = job.get("address")
        place = f"<p class=\"addr-line\">기관 주소 · {e(where)}</p>" if where else ""
        also = "으로도 접수할 수 있어요" if cards else "으로 접수해요"
        cards.append(f"""<div class="apply-card"><p class="label">{ways}{also}</p>{place}
<p class="tip">받는 곳과 접수 시간은 공고 내용의 접수 방법을 확인하세요.</p></div>""")
    if not cards:
        if job["files"]:
            msg = "접수 방법은 첨부된 공고문에 있어요. 아래 공고문을 내려받아 확인하세요."
        elif job.get("contact"):
            msg = "공고에 접수 방법이 나와 있지 않아요. 아래 연락처로 문의해 지원 방법을 확인하세요."
        else:
            msg = f"공고에 접수 방법이 나와 있지 않아요. {job['org']}에 직접 문의해 지원 방법을 확인하세요."
        cards.append(f'<div class="apply-card"><p class="label">지원 방법을 확인해 주세요</p><p class="tip">{e(msg)}</p></div>')

    extra = []
    if job.get("documents"):
        extra.append(f"<div><dt>제출 서류</dt><dd>{e(job['documents'])}</dd></div>")
    contact = job.get("contact")
    if contact:
        phone = PHONE.search(contact)
        value = e(contact)
        if phone:
            digits = re.sub(r"\D", "", phone.group(0))
            value = value.replace(e(phone.group(0)), f'<a href="tel:{digits}">{e(phone.group(0))}</a>', 1)
        extra.append(f"<div><dt>문의</dt><dd>{value}</dd></div>")
    if extra:
        cards.append(f'<dl class="facts apply-facts">{"".join(extra)}</dl>')
    return "\n".join(cards)


def short(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1] + "…"


def distance_km(a: dict, b: dict) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a["latitude"], a["longitude"], b["latitude"], b["longitude"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def nearby_jobs(job: dict, jobs: list[dict], limit: int = 3, radius_km: float = 60) -> list[tuple[dict, float]]:
    if not job["has_place"]:
        return []
    found = [
        (other, distance_km(job, other))
        for other in jobs
        if other is not job and other["has_place"]
    ]
    return sorted([f for f in found if f[1] <= radius_km], key=lambda f: f[1])[:limit]


# --- page parts -----------------------------------------------------------------

@functools.cache
def asset_version(name: str) -> str:
    """A short hash of a static file, so browsers fetch it again after it changes."""
    path = STATIC_DIR / name if (STATIC_DIR / name).is_file() else TEST_STATIC_DIR / name
    return hashlib.sha256(path.read_bytes()).hexdigest()[:10]


def page(title: str, description: str, body: str, *, root: str, config: dict, canonical: str | None,
         active: str, extra_head: str = "", body_attrs: str = "") -> str:
    adsense = config.get("adsense_client")
    head_ads = (
        f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={e(adsense)}" crossorigin="anonymous"></script>'
        if adsense else ""
    )
    site_config = {"kakaoKey": config.get("kakao_js_key") or "", "alertEndpoint": config.get("alert_endpoint") or ""}
    private = config.get("private")
    test = config.get("test")
    private_head = '<meta name="robots" content="noindex, nofollow">' if private or test else ""
    private_bar = (
        '<div class="private-bar" role="note">비공개 미리보기 · 해외 공고와 준비 중인 서비스 포함 · 배포하지 마세요</div>'
        if private else '<div class="private-bar" role="note">테스트 페이지 · 관리자만 볼 수 있어요</div>' if test else ""
    )
    test_css = f'<link rel="stylesheet" href="{root}assets/large.css?v={asset_version("large.css")}">' if test else ""
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
{f'<link rel="canonical" href="{e(canonical)}">' if canonical else ""}
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:type" content="website">
<link rel="stylesheet" href="{FONT_CSS}">
<link rel="stylesheet" href="{root}assets/styles.css?v={asset_version('styles.css')}">
{test_css}
{head_ads}
{private_head}
{extra_head}
</head>
<body{body_attrs}>
{private_bar}
{header(root, active, services_on(config), alerts_on(config), bool(test))}
{body}
{footer(root)}
<script>window.SITE = {json_for_script(site_config)};</script>
<script src="{root}assets/app.js?v={asset_version('app.js')}" defer></script>
</body>
</html>
"""


def services_on(config: dict) -> bool:
    """Paid services (첨삭, 시강 교안 AI) are not launched yet: the public site
    shows only the free job board. --with-services turns them on; the private
    build always shows them so they can be worked on."""
    return bool(config.get("services") or config.get("private"))


def alerts_on(config: dict) -> bool:
    """The job alert stays hidden until ALERT_ENDPOINT stores sign-ups: a form
    that keeps nothing would promise mail that never comes."""
    return bool(config.get("alert_endpoint"))


def header(root: str, active: str, with_services: bool = False, with_alerts: bool = False,
           with_review: bool = False) -> str:
    links = [("jobs", f"{root}index.html", "채용공고"), ("pay", f"{root}pay.html", "실수령 계산기")]
    if with_review:
        links.append(("review", f"{root}rating.html", "근무 후기"))
    if with_services:
        links += [
            ("resume", f"{root}resume.html", "이력서·자소서 첨삭"),
            ("demo", f"{root}demo.html", "시강 교안 AI"),
        ]
    nav = "".join(
        f'<a href="{href}"{" aria-current=\"page\"" if key == active else ""}>{label}</a>' for key, href, label in links
    )
    return f"""<header class="top"><div class="wrap">
<a class="logo" href="{root}index.html">{SITE_NAME}</a>
<nav class="nav" aria-label="주요 메뉴">{nav}</nav>
{f'<a class="btn btn-soft" href="{root}index.html#alert">알림 받기</a>' if with_alerts else ""}
</div></header>"""


def footer(root: str) -> str:
    return f"""<footer class="foot"><div class="wrap">
<strong>{SITE_NAME}</strong>
<span>직업정보제공사업 신고번호 [신고 후 기재]</span>
</div></footer>"""


def ad_slot(config: dict, kind: str, label: str) -> str:
    # No ads run yet, so nothing is drawn by default. Once AdSense is approved,
    # ADSENSE_CLIENT turns on Auto ads, which place their own units. The dashed
    # boxes only show with --ad-slots, to review where ads would sit.
    if not config.get("ad_slots") or config.get("adsense_client") or config.get("private"):
        return ""
    tag = "li" if kind == "infeed" else "div"
    return f'<{tag} class="ad-slot {kind}" aria-label="광고">{label}</{tag}>'


def posted_date(job: dict) -> str:
    return (job.get("posted_at") or job.get("first_seen_at") or "")[:10]


def job_row(job: dict, root: str, review: bool = False) -> str:
    chips = "".join(f'<span class="chip">{e(c)}</span>' for c in job["chips"])
    search = " ".join(str(x) for x in (job.get("title"), job["org"], job["place"], job.get("location_text")) if x).lower()
    lat = job["latitude"] if job["has_place"] else ""
    lng = job["longitude"] if job["has_place"] else ""
    review_attr = f' data-review="{e(job["institution_name"])}"' if review and job.get("institution_name") else ""
    return f"""<li class="job-row" data-id="{job['job_id']}" data-scope="{job['scope']}" data-newcomer="{1 if job.get('newcomer_ok') == 1 else 0}" data-demo="{1 if job.get('demo_lesson') == 1 else 0}" data-lat="{lat}" data-lng="{lng}" data-deadline="{e(job.get('deadline') or '')}" data-posted="{e(posted_date(job))}" data-name="{e(job['org'])}" data-title="{e(job.get('title'))}" data-org="{e(job['org'] + ' · ' + job['place'])}" data-search="{e(search)}"{review_attr}>
<button type="button" class="pick">
<span class="badge {job['badge_class']}" data-badge="{e(job.get('deadline') or '')}">{e(job['badge'])}</span>
<span class="job-title">{e(job.get('title'))}</span>
<span class="job-org">{e(job['org'])} · {e(job['place'])}</span>
<span class="chips">{chips}</span>
</button>
<a class="go" href="{root}{job['path']}" aria-label="{e(job['org'])} 공고 자세히 보기">자세히</a>
</li>"""


# --- pages -------------------------------------------------------------------

def render_index(jobs: list[dict], config: dict, collected_at: dt.datetime) -> str:
    counts = {scope: sum(1 for j in jobs if j["scope"] == scope) for scope in ("domestic", "overseas", "online")}
    rows = [job_row(job, "", bool(config.get("test"))) for job in jobs]
    if len(rows) > 3:
        rows.insert(3, ad_slot(config, "infeed", "광고"))
    countries: dict[str, int] = {}
    for job in jobs:
        if job["scope"] == "overseas":
            countries[job["place"]] = countries.get(job["place"], 0) + 1
    country_cards = "".join(
        f'<div class="country"><p>{e(name)}</p><strong>{count}개</strong></div>'
        for name, count in sorted(countries.items(), key=lambda kv: -kv[1])
    )
    show_overseas = bool(config.get("private"))
    scopes = [("all", "전체", len(jobs)), ("domestic", "국내", counts["domestic"])]
    if show_overseas:
        scopes.append(("overseas", "해외", counts["overseas"]))
    scopes.append(("online", "온라인", counts["online"]))
    scope_buttons = "".join(
        f'<button type="button" data-scope-btn="{key}" aria-pressed="{"true" if key == "all" else "false"}">{label} {count}</button>'
        for key, label, count in scopes
    )
    countries_view = f"""<div class="alt-view" data-view="countries" hidden>
<h2>나라별로 볼게요</h2>
<p>해외 공고는 지역보다 나라가 먼저 중요해요. 비자·항공·숙소 지원은 공고 안에서 확인하세요.</p>
<div class="countries">{country_cards or '<p class="fine">지금 열린 해외 공고가 없어요.</p>'}</div>
</div>""" if show_overseas else ""
    services = service_blocks(config, "")
    alert_section = """<section id="alert" class="callout alert-box" aria-labelledby="alertTitle">
<h2 id="alertTitle">지금 고른 조건 그대로<br>새 공고를 알려 드릴게요</h2>
<p class="desc"><span data-filter-summary>전체</span> · 새 공고와 마감 3일 전에만, 일주일에 두 번 이하로 보내요.</p>
<form class="alert-form" data-alert-form>
<label><span class="sr-only">이메일</span><input type="email" name="email" required placeholder="이메일 주소" autocomplete="email"></label>
<button type="submit" class="btn btn-primary">알림 받기</button>
</form>
<p class="alert-done" data-alert-done role="status" hidden></p>
</section>""" if alerts_on(config) else ""
    body = f"""<main class="wrap" data-board>
<section class="hero" aria-labelledby="headline">
<div>
<p class="eyebrow">{collected_at.month}월 {collected_at.day}일 {collected_at.hour}시에 새로 모았어요</p>
<h1 id="headline" class="title-xl">지금 지원할 수 있는<br>한국어 강사 공고 <em>{len(jobs)}개</em></h1>
</div>
<div class="filters">
<div class="seg" role="group" aria-label="근무 형태">{scope_buttons}</div>
<button type="button" class="toggle" data-toggle="newcomer" aria-pressed="false">신입 가능</button>
<button type="button" class="toggle" data-toggle="demo" aria-pressed="false">모의수업 있음</button>
<button type="button" class="toggle" data-toggle="saved" aria-pressed="false">저장한 공고 <span data-saved-count></span></button>
<label class="search"><span class="sr-only">기관명이나 지역 검색</span><input type="search" data-search-input placeholder="기관명, 지역으로 찾기"></label>
</div>
</section>

<div class="board">
<section class="map-panel" aria-label="지도">
<div class="map-box" data-view="map">
<div id="map"></div>
<p class="map-note">지도를 불러오는 중이에요</p>
</div>
{countries_view}
<div class="alt-view" data-view="online" hidden>
<h2>온라인·재택 공고는 장소가 없어요</h2>
<p>오른쪽 목록에서 수업 시간대와 학습자 국가를 확인하세요.</p>
</div>
</section>

<section class="list-panel" aria-labelledby="listTitle">
<div class="panel-head"><h2 id="listTitle">공고 목록</h2><span data-count>{len(jobs)}개</span></div>
<div class="sort-bar" role="group" aria-label="정렬">
<button type="button" data-sort="deadline" aria-pressed="true">마감순</button>
<button type="button" data-sort="newest" aria-pressed="false">최신순</button>
<button type="button" data-sort="name" aria-pressed="false">가나다순</button>
<button type="button" data-sort="near" aria-pressed="false">가까운순</button>
</div>
<p class="sort-note" data-sort-note role="status" hidden></p>
<p class="local-note" data-saved-note hidden>저장한 공고와 지원 표시는 <strong>이 브라우저에만</strong> 남아요. 다른 기기나 다른 브라우저에서는 보이지 않고, 방문 기록·쿠키를 지우면 사라져요.</p>
<div class="empty" data-empty hidden><p data-empty-title>조건에 맞는 공고가 아직 없어요</p><p data-empty-desc>{"알림을 켜 두면 올라오는 대로 알려 드려요." if alerts_on(config) else "다른 조건으로 찾아보세요."}</p></div>
<ul class="jobs">{"".join(rows)}</ul>
</section>
</div>

<div class="row">
{alert_section}
{services}
{ad_slot(config, "display", "광고")}
</div>
</main>"""
    description = f"한국어 강사·한국어교원 채용 공고 {len(jobs)}개. 어학당, 대학 언어교육원, 가족센터, 교육청 공고를 지도와 마감일 순으로 모았어요."
    return page(f"{SITE_NAME} · 한국어 강사 채용 공고 모음", description, body, root="", config=config,
                canonical=absolute(config, "index.html"), active="jobs")


def service_blocks(config: dict, root: str) -> str:
    if not services_on(config):
        return ""
    blocks = []
    if SERVICE_LINKS["ebook"]:
        blocks.append(f"""<section class="callout service" aria-labelledby="ebookTitle">
<p class="kicker">전자책</p><h2 id="ebookTitle">어학당 면접, 이 질문은 꼭 나와요</h2>
<p class="desc">기관 유형별 질문과 15분 시강 구성법</p>
<a class="btn btn-line" href="{e(SERVICE_LINKS['ebook'])}">미리보기</a></section>""")
    blocks.append(f"""<section class="callout service" aria-labelledby="resumeBlock">
<p class="kicker">이력서·자소서 첨삭</p><h2 id="resumeBlock">지원 전에 서류부터 다듬어 보세요</h2>
<p class="desc">한국어 강사 채용을 아는 사람이 이력서와 자기소개서를 기관에 맞춰 고쳐 드려요.</p>
<a class="btn btn-line" href="{root}resume.html">첨삭 알아보기</a></section>""")
    blocks.append(f"""<section class="callout service" aria-labelledby="demoBlock">
<p class="kicker">시강 교안 AI</p><h2 id="demoBlock">모의수업 교안, 초안부터 잡아 보세요</h2>
<p class="desc">수준과 문법만 고르면 다섯 단계 교안 초안이 나와요.</p>
<a class="btn btn-line" href="{root}demo.html">무료로 만들어 보기</a></section>""")
    return "\n".join(blocks)


def render_job(job: dict, jobs: list[dict], config: dict, today: dt.date) -> str:
    root = "../"
    facts = [
        ("마감", deadline_text(job.get("deadline"))),
        ("근무지", job.get("address") if job["scope"] == "domestic" and job.get("address") else job["place"]),
        ("기관 유형", INSTITUTION_TYPE_LABELS.get(job.get("institution_type") or "")),
        ("지원 자격", job.get("qualification")),
        ("경력", job.get("experience_required") or ("없어도 돼요" if job.get("newcomer_ok") == 1 else None)),
        ("근무 기간", job.get("work_period")),
        ("근무 시간", job.get("work_hours")),
        ("강의료", job.get("salary_text")),
        ("전형", job.get("schedule") or ("서류 → 모의수업" if job.get("demo_lesson") == 1 else None)),
        ("제출 서류", job.get("documents")),
        ("접수 방법", job.get("how_to_apply") or ("이메일 접수" if job.get("apply_email") else None)),
        ("문의", job.get("contact")),
        ("지원 사항", job.get("benefits")),
    ]
    pay = pay_query(job)
    pay_link = f' <a class="pay-link" href="{root}pay.html?{e(pay)}">실수령 계산</a>' if pay else ""
    fact_rows = "".join(
        f"<div><dt>{e(k)}</dt><dd>{e(v)}{pay_link if k == '강의료' else ''}</dd></div>" for k, v in facts if v
    )
    chips = "".join(f'<span class="chip">{e(c)}</span>' for c in job["chips"])

    map_section = ""
    if job["has_place"]:
        map_section = f"""<section class="sec" aria-labelledby="mapTitle">
<h2 id="mapTitle">어디서 일하나요</h2>
<p class="place-line">{e(job.get('address') or job['place'])}</p>
<div class="mini-map" data-mini-map data-lat="{job['latitude']}" data-lng="{job['longitude']}" data-label="{e(job['org'])}"><p class="map-note" hidden></p></div>
</section>"""

    steps = ""
    demo_cta = ""
    if job.get("demo_lesson") == 1:
        steps = """<section class="sec" aria-labelledby="stepsTitle"><h2 id="stepsTitle">이렇게 뽑아요</h2>
<ol class="steps"><li><span class="n">1</span>서류 심사</li>
<li class="on"><span class="n">2</span><span>모의수업 <span class="hint">· 여기서 많이 갈려요</span></span></li>
<li><span class="n">3</span>최종 합격</li></ol></section>"""
        if services_on(config):
            demo_cta = f"""<section class="cta-blue" aria-labelledby="demoTitle"><div class="grow">
<p class="kicker">모의수업이 있는 공고예요</p>
<h2 id="demoTitle">시강 교안 초안,<br>3분이면 만들 수 있어요</h2>
<p class="desc">수준과 문법만 고르면 돼요. 무료로 3번까지.</p></div>
<a class="btn btn-lg" href="{root}demo.html">무료로 만들어 보기</a></section>"""

    # Everything needed to apply is on this page: the email, our own copies of
    # the notice files, and the full notice. Nothing links to where it came from.
    email_block = apply_guide(job)
    files_block = ""
    if job["files"]:
        items = "".join(
            f'<li><a href="{root}files/{e(path)}" download="{e(name)}">{e(name)}</a></li>' for name, path in job["files"]
        )
        files_block = f'<div class="files"><h3>공고문·지원 양식</h3><ul>{items}</ul></div>'
    notice = notice_html(job.get("body_text"))
    if notice:
        notice_section = f'<section class="sec" aria-labelledby="noticeTitle"><h2 id="noticeTitle">공고 내용</h2><div class="notice">{notice}</div></section>'
    else:
        notice_section = f"""<section class="sec" aria-labelledby="sumTitle"><h2 id="sumTitle">이런 공고예요</h2>
<p class="prose">{e(job.get('summary') or '자세한 내용은 첨부된 공고문을 확인해 주세요.')}</p></section>"""
    mentoring = SERVICE_LINKS["mentoring"]
    # After "지원했어요": with services, prepare for the demo lesson; without,
    # point to the alert once it runs, else to the other jobs.
    if services_on(config):
        applied_text = "모의수업 연락이 오기 전에 교안을 미리 준비해 두세요."
        applied_link = (
            f'<a class="btn btn-dark" href="{e(mentoring)}">리허설 일정 보기</a>' if mentoring
            else f'<a class="btn btn-dark" href="{root}demo.html">교안 준비하기</a>'
        )
    elif alerts_on(config):
        applied_text = "다른 공고도 놓치지 않게 새 공고 알림을 켜 두세요."
        applied_link = f'<a class="btn btn-dark" href="{root}index.html#alert">알림 받기</a>'
    else:
        applied_text = "근처의 다른 공고도 함께 살펴보세요."
        applied_link = f'<a class="btn btn-dark" href="{root}index.html">다른 공고 보기</a>'

    near = nearby_jobs(job, jobs)
    near_items = "".join(
        f'<li><a href="{other["job_id"]}.html"><span class="when {other["badge_class"]}">{e(other["badge"])} · 약 {dist:.0f}km</span>'
        f'<span class="who">{e(other["org"])}</span></a></li>'
        for other, dist in near
    )
    near_block = (
        f'<section class="callout" aria-labelledby="nearTitle"><h2 id="nearTitle">근처 공고</h2><ul class="side-list">{near_items}</ul></section>'
        if near_items else ""
    )
    # The free alert is what brings people back; every job page offers it.
    alert_block = f"""<section class="callout" aria-labelledby="sideAlertTitle"><p class="kicker">무료 알림</p>
<h2 id="sideAlertTitle">이런 공고가 올라오면<br>바로 알려 드릴게요</h2>
<p class="desc">원하는 지역과 조건으로 새 공고와 마감 3일 전 소식을 받아 보세요.</p>
<a class="btn btn-primary" href="{root}index.html#alert">알림 받기</a></section>"""
    side = [alert_block if alerts_on(config) else "", near_block]
    if mentoring and services_on(config):
        side.insert(0, f"""<section class="callout" aria-labelledby="mentorTitle"><p class="kicker">1:1 커리어 멘토링</p>
<h2 id="mentorTitle">면접 날짜가 잡혔다면<br>시강 리허설부터</h2>
<p class="desc">현직 강사가 교안과 시연을 보고 고칠 점을 짚어 드려요.</p>
<a class="btn btn-dark" href="{e(mentoring)}">일정 고르기</a></section>""")
    side.append(service_blocks(config, root))
    if config.get("test") and job.get("institution_name"):
        org = e(urllib.parse.quote(job["institution_name"]))
        side.insert(0, f"""<section class="callout" aria-labelledby="reviewTitle"><p class="kicker">근무 후기</p>
<h2 id="reviewTitle">{e(job['org'])},<br>일해 본 사람들은 어땠을까요?</h2>
<p class="desc">현직·전직 강사들이 남긴 점수와 한마디를 볼 수 있어요.</p>
<div class="apply-row"><a class="btn btn-review" href="{root}rating.html?org={org}">후기 보기</a>
<a class="btn btn-line" href="{root}review.html?org={org}">나도 후기 남기기</a></div></section>""")

    side.insert(0, pay_box(job, root))

    body = f"""<main class="wrap">
<a class="back" href="{root}index.html">‹ 지도로 돌아가기</a>
<div class="detail">
<div class="detail-main">
<section class="sec" aria-labelledby="jobTitle">
<span class="badge {job['badge_class']}" data-badge="{e(job.get('deadline') or '')}">{e(job['badge'])}</span>
<h1 id="jobTitle" class="title-xl" style="margin-top: 14px">{e(job.get('title'))}</h1>
<p class="meta">{e(job['org'])} · {e(job['place'])}</p>
<div class="chips" style="margin-top: 20px">{chips}</div>
</section>
<section class="sec" aria-labelledby="factsTitle"><h2 id="factsTitle">한눈에 보기</h2><dl class="facts">{fact_rows}</dl></section>
{map_section}
{notice_section}
{steps}
{demo_cta}
<section class="sec" aria-labelledby="applyTitle"><h2 id="applyTitle">지원하기</h2>
{email_block}
{files_block}
<div class="apply-row">
<button type="button" class="btn btn-gray btn-lg" data-applied>지원했어요</button>
<button type="button" class="btn btn-gray btn-lg" data-save aria-pressed="false">저장</button></div>
<p class="local-note">저장과 지원 표시는 로그인 없이 <strong>이 브라우저에만</strong> 남아요. 다른 기기에서는 보이지 않고, 방문 기록·쿠키를 지우면 사라져요. 저장한 공고는 첫 화면의 <strong>저장한 공고</strong>에서 모아 볼 수 있어요.</p>
<div class="applied-note" data-applied-note role="status" hidden><p><strong>지원 완료, 수고했어요.</strong> {applied_text}</p>
{applied_link}</div></section>
</div>
<aside class="detail-side" aria-label="지원 준비">{"".join(side)}</aside>
</div>
</main>"""
    jsonld = f'<script type="application/ld+json">{json_for_script(job_posting(job, config))}</script>'
    description = job.get("summary") or f"{job['org']} 한국어 강사 채용 공고"
    return page(f"{job.get('title')} · {job['org']} | {SITE_NAME}", short(description, 150), body, root=root,
                config=config, canonical=absolute(config, job["path"]), active="jobs", extra_head=jsonld,
                body_attrs=f' data-job-id="{job["job_id"]}"')


def job_posting(job: dict, config: dict) -> dict:
    """schema.org JobPosting for Google's job search. The description is our own summary."""
    posted = posted_date(job)
    data = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": job.get("title"),
        "description": job.get("summary") or job.get("title"),
        "datePosted": posted or None,
        "hiringOrganization": {"@type": "Organization", "name": job["org"]},
        "url": absolute(config, job["path"]),
    }
    deadline = job.get("deadline")
    if deadline and deadline != "rolling":
        data["validThrough"] = f"{deadline}T23:59:59+09:00"
    if job["scope"] == "online":
        data["jobLocationType"] = "TELECOMMUTE"
        data["applicantLocationRequirements"] = {"@type": "Country", "name": "South Korea"}
    else:
        address = {"@type": "PostalAddress", "addressCountry": "KR" if job["scope"] == "domestic" else (job.get("country") or "")}
        if job["scope"] == "domestic":
            address["addressRegion"] = job.get("location_text") or ""
            if job.get("address"):
                address["streetAddress"] = job["address"]
        data["jobLocation"] = {"@type": "Place", "address": address}
    return {k: v for k, v in data.items() if v is not None}


def render_resume(config: dict) -> str:
    """이력서·자기소개서 첨삭: a placeholder page that takes pre-registrations."""
    offers = [
        ("이력서 첨삭", "한국어 교육 경력, 자격, 학력을 기관이 보는 순서로 다시 배치하고, 빠진 항목을 짚어 드려요."),
        ("자기소개서 첨삭", "지원 동기와 교수 경험을 그 기관의 학습자와 과정에 맞춰 구체적으로 고쳐 드려요."),
        ("강의계획서·교안 점검", "서류와 함께 내는 강의계획서나 시강 교안이 있다면 같이 봐 드려요."),
    ]
    offer_cards = "".join(
        f'<section class="callout service"><h2>{e(t)}</h2><p class="desc">{e(d)}</p></section>' for t, d in offers
    )
    steps = [
        ("서류 보내기", "지원할 공고와 지금 쓴 이력서·자기소개서를 보내요."),
        ("첨삭", "공고 요건에 맞춰 고칠 곳과 이유를 문서에 바로 표시해요."),
        ("다시 보기", "고친 서류를 한 번 더 봐 드려요."),
    ]
    step_items = "".join(
        f'<li><span class="n">{i}</span><span><strong>{e(t)}</strong> <span class="hint">· {e(d)}</span></span></li>'
        for i, (t, d) in enumerate(steps, 1)
    )
    body = f"""<main class="wrap">
<div class="detail">
<div class="detail-main">
<section class="sec" aria-labelledby="resumeHead">
<p class="eyebrow">준비 중인 서비스예요</p>
<h1 id="resumeHead" class="title-xl">한국어 강사 지원 서류,<br>기관에 맞춰 다듬어 드려요</h1>
<p class="prose">어학당, 세종학당, 가족센터, 해외 대학은 보는 것이 서로 달라요. 지원하려는 공고를 기준으로 이력서와 자기소개서를 고쳐 드려요.</p>
</section>
<div class="row" style="margin-top: 32px">{offer_cards}</div>
<section class="sec" aria-labelledby="stepsTitle"><h2 id="stepsTitle">이렇게 진행해요</h2><ol class="steps">{step_items}</ol></section>
<section class="sec" aria-labelledby="priceTitle"><h2 id="priceTitle">가격</h2>
<p class="prose">가격과 진행 기간은 서비스를 열 때 안내해 드려요.</p></section>
</div>
<aside class="detail-side" aria-label="사전 신청">
<section class="callout" aria-labelledby="preTitle">
<p class="kicker">사전 신청</p>
<h2 id="preTitle">서비스가 열리면 먼저 알려 드릴게요</h2>
<p class="desc">이메일을 남겨 주시면 오픈 소식과 첫 신청 혜택을 보내 드려요.</p>
<form class="alert-form" data-alert-form data-kind="resume">
<label><span class="sr-only">이메일</span><input type="email" name="email" required placeholder="이메일 주소" autocomplete="email"></label>
<button type="submit" class="btn btn-primary">사전 신청</button>
</form>
<p class="alert-done" data-alert-done role="status" hidden></p>
</section>
</aside>
</div>
</main>"""
    return page(f"이력서·자소서 첨삭 · {SITE_NAME}", "한국어 강사 지원용 이력서와 자기소개서를 기관에 맞춰 첨삭해 드려요.", body,
                root="", config=config, canonical=absolute(config, "resume.html"), active="resume")


def render_demo(config: dict) -> str:
    def options(group: str, values: list[str], chosen: str) -> str:
        return "".join(
            f'<button type="button" class="opt" data-opt="{group}" aria-pressed="{"true" if v == chosen else "false"}">{v}</button>'
            for v in values
        )

    steps = [
        ("도입", "2분", "주말에 한 일을 묻고, 운동이나 요리처럼 할 줄 아는 일을 사진으로 떠올리게 해요.", "여러분, 수영할 수 있어요? 오늘은 이렇게 물어보는 방법을 배워요."),
        ("제시", "4분", "받침이 없으면 -ㄹ 수 있다, 있으면 -을 수 있다. 동사 카드(가다, 먹다, 만들다)로 보여 주고 ㄹ 탈락 동사는 따로 표시해요.", "먹다는 받침이 있어요. 그래서 먹을 수 있어요."),
        ("연습", "4분", "그림 카드를 보고 할 수 있다/없다 문장 만들기. 짝과 묻고 답하며 교사가 오류를 바로 고쳐 줘요.", "피아노를 칠 수 있어요? 아니요, 칠 수 없어요."),
        ("활용", "4분", "“우리 반 장기 자랑” 설문으로 할 수 있는 것 세 가지를 조사해 한 문장으로 발표해요.", "민수 씨는 기타를 칠 수 있어요. 그런데 수영은 할 수 없어요."),
        ("마무리", "1분", "배운 형태를 판서로 정리하고, 다음 시간 -(으)ㄹ 줄 알다와 이어서 예고해요.", "다음 시간에는 할 줄 알아요도 배워 볼 거예요."),
    ]
    plan = "".join(
        f'<li><div class="step"><strong>{n}</strong><span>{t}</span></div><div class="body">{p}<p class="say">“{s}”</p></div></li>'
        for n, t, p, s in steps
    )
    body = f"""<main class="wrap" data-demo-page>
<a class="back" href="index.html">‹ 공고 보러 가기</a>
<div class="demo">
<section class="demo-form" aria-labelledby="demoHead">
<div><h1 id="demoHead" class="title-xl demo-head">모의수업 교안,<br>초안부터 같이 잡아 볼게요</h1>
<p class="fine demo-free">가입 없이 3번까지 무료예요.</p></div>
<div role="group" aria-labelledby="levelLabel"><span id="levelLabel" class="label">학습자 수준</span>
<div class="grid3">{options("level", ["초급 1", "초급 2", "중급 1", "중급 2", "고급 1", "고급 2"], "초급 2")}</div></div>
<label><span class="label">가르칠 문법이나 주제</span><input class="field" type="text" data-topic value="-(으)ㄹ 수 있다/없다"></label>
<div role="group" aria-labelledby="timeLabel"><span id="timeLabel" class="label">시강 시간</span>
<div class="grid3">{options("time", ["10분", "15분", "20분"], "15분")}</div></div>
<label><span class="label">학습자 <span style="font-weight: 400; color: var(--text-4)">(선택)</span></span><input class="field" type="text" placeholder="예: 이주배경 청소년, 베트남 대학생"></label>
<button type="button" class="btn btn-primary btn-lg" data-generate>교안 초안 만들기</button>
<p class="fine" style="text-align: center; margin-top: -12px">무료로 <span data-left>3</span>번 더 만들 수 있어요</p>
</section>
<section class="demo-out" aria-live="polite" aria-labelledby="resultTitle">
<div class="callout" data-waiting><h2 id="resultTitle">여기에 초안이 나와요</h2>
<p class="desc">수업이 도입·제시·연습·활용·마무리 다섯 단계로 나뉘고, 단계마다 시간과 교사가 할 말이 붙어요.</p></div>
<div class="callout" data-result hidden>
<h2 data-plan-heading></h2>
<p class="fine">지금은 미리보기용 예시 교안이에요. 실제 생성 기능은 준비 중이에요.</p>
<ol class="plan">{plan}</ol>
</div>
</section>
</div>
</main>"""
    return page(f"시강 교안 AI · {SITE_NAME}", "한국어 강사 모의수업(시강) 교안 초안을 만들어 보세요.", body,
                root="", config=config, canonical=absolute(config, "demo.html"), active="demo")


def review_orgs(conn: sqlite3.Connection) -> list[str]:
    """Every institution the collector has seen, for the review page's search."""
    names = {
        " ".join(name.split())
        for (name,) in conn.execute("SELECT DISTINCT institution_name FROM jobs WHERE institution_name IS NOT NULL")
    }
    return sorted((n for n in names if 1 < len(n) <= review_items.MAX_ORG), key=lambda n: (n.replace(" ", ""), n))


def review_page(config: dict, orgs: list[str], *, script: str, title: str, active: str) -> str:
    """Shell for the two 근무 후기 pages (test build only); the script draws the rest."""
    data = {**review_items.page_data(), "orgs": orgs}
    body = f"""<main class="wrap review" data-review>
<div data-review-box aria-live="polite"><p class="rv-note">불러오는 중이에요. 자바스크립트가 꺼져 있으면 볼 수 없어요.</p></div>
<script type="application/json" id="reviewData">{json_for_script(data)}</script>
</main>
<script src="assets/{script}?v={asset_version(script)}" defer></script>"""
    head = f'<link rel="stylesheet" href="assets/review.css?v={asset_version("review.css")}">'
    return page(f"{title} · {SITE_NAME}", "한국어 강사들이 일해 본 기관의 근무 후기를 모았어요.", body, root="", config=config,
                canonical=None, active=active, extra_head=head)


def render_rating(config: dict, orgs: list[str]) -> str:
    """One institution's results (?org=), or a search for one."""
    return review_page(config, orgs, script="rating.js", title="근무 후기", active="review")


def render_review(config: dict, orgs: list[str]) -> str:
    """The form: area → statement → score, any of it, finished whenever."""
    return review_page(config, orgs, script="review.js", title="나도 후기 남기기", active="review")


RATE_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{4,6})\s*원")
WEEKLY_HOURS_RE = re.compile(r"주\s*(\d{1,2}(?:\.\d)?)\s*시간")


def hourly_rates(job: dict) -> list[int]:
    """The hourly fees in won a domestic notice names (박사·석사·학사 or 경력별
    may list several), in the notice's order, at most four."""
    salary = job.get("salary_text") or ""
    if job["scope"] == "overseas" or not re.search(r"시간|시급", salary):
        return []
    rates: list[int] = []
    for n in (int(m.replace(",", "")) for m in RATE_RE.findall(salary)):
        if 10_000 <= n <= 200_000 and n not in rates:
            rates.append(n)
    return rates[:4]


def weekly_hours(job: dict) -> str | None:
    """주 N시간 from the notice's working hours, when it says so."""
    hours = WEEKLY_HOURS_RE.search(job.get("work_hours") or "")
    return hours[1] if hours and 0 < float(hours[1]) <= 60 else None


def pay_query(job: dict) -> str | None:
    """?rate=&hours=&from= for the 실수령 계산기, when the notice names an hourly
    fee in won (the first one, if it lists several)."""
    rates = hourly_rates(job)
    if not rates:
        return None
    query: dict[str, object] = {"rate": rates[0]}
    if weekly_hours(job):
        query["hours"] = weekly_hours(job)
    query["from"] = job["org"]
    return urllib.parse.urlencode(query)


def pay_box(job: dict, root: str) -> str:
    """The job page's side calculator: 주당 시수 × this notice's hourly fee →
    주급 and 월급, take-home at 3.3% and before tax. pay.js fills it in."""
    rates = hourly_rates(job)
    if not rates:
        return ""
    if len(rates) > 1:
        buttons = "".join(
            f'<button type="button" data-mini-rate="{r}" aria-pressed="{"true" if i == 0 else "false"}">{r:,}원</button>'
            for i, r in enumerate(rates)
        )
        rate_html = f'<div class="pm-rates" role="group" aria-label="시급 고르기">{buttons}</div>'
    else:
        rate_html = f'<p class="pm-rate">시급 <strong>{rates[0]:,}원</strong></p>'
    hours = weekly_hours(job) or ""
    return f"""<section class="callout pay-mini" data-pay-mini data-rate="{rates[0]}" data-from="{e(job['org'])}" aria-labelledby="payMiniTitle">
<p class="kicker">실수령 계산</p>
<h2 id="payMiniTitle">이 공고 시급이면<br>얼마 받을까요?</h2>
{rate_html}
<label class="pm-hours"><span>주당 시수</span><span class="pm-field"><input type="text" inputmode="decimal" autocomplete="off" placeholder="예: 12" value="{e(hours)}" data-mini-hours><span>시간</span></span></label>
<dl class="pm-out" data-mini-out hidden>
<div><dt>주급</dt><dd><strong data-mini-week></strong><span>세전 <span data-mini-week-gross></span></span></dd></div>
<div><dt>월급</dt><dd><strong data-mini-month></strong><span>세전 <span data-mini-month-gross></span></span></dd></div>
</dl>
<p class="pm-note">실수령은 3.3% 떼는 프리랜서 기준이에요. 한 달은 4.33주로 계산해요.</p>
<a class="pm-more" href="{root}pay.html?{e(pay_query(job))}" data-mini-more>4대보험·공제 내역 자세히 보기 ›</a>
</section>
<script src="{root}assets/pay.js?v={asset_version('pay.js')}" defer></script>"""


def render_pay(config: dict) -> str:
    """강사료 실수령 계산기: hourly fee × hours → what one week and one month
    pay, before and after deductions, for the chosen contract (프리랜서 3.3%
    or 4대보험 근로자). Deductions and formulas sit folded below. The math
    lives in pay.js, which tests run under node."""
    body = """<main class="wrap pay" data-pay>
<a class="back" href="index.html">‹ 공고 보러 가기</a>
<h1 class="title-xl">강사료, 실제로 얼마 받을까요?</h1>
<p class="pay-sub">시간당 강사료와 시수를 넣으면 한 주, 한 달에 손에 쥐는 돈을 보여 드려요.</p>
<p class="pay-from" data-from hidden><strong></strong> 공고의 강사료로 채웠어요. 고쳐서 계산해 보세요.</p>
<div class="pay-inputs">
<label><span class="label">시간당 강사료</span>
<span class="pay-field"><input class="field" type="text" inputmode="numeric" autocomplete="off" data-rate value="35,000"><span class="unit">원</span></span></label>
<div><div class="pay-label-row"><label class="label" for="payHours">시수</label>
<span class="pay-seg" role="group" aria-label="시수 단위"><button type="button" data-unit="week" aria-pressed="true">주당</button><button type="button" data-unit="month" aria-pressed="false">한 달</button></span></div>
<span class="pay-field"><input class="field" id="payHours" type="text" inputmode="decimal" autocomplete="off" data-hours value="12"><span class="unit" data-hours-unit>시간/주</span></span></div>
</div>
<div class="pay-contract"><span class="label" id="contractLabel">계약 형태</span>
<div class="pay-seg pay-seg-lg" role="group" aria-labelledby="contractLabel">
<button type="button" data-contract="freelance" aria-pressed="true">프리랜서 <small>3.3%</small></button><button type="button" data-contract="employee" aria-pressed="false">근로자 <small>4대보험</small></button></div></div>
<section class="pay-result" data-out aria-live="polite">
<div class="pay-period"><h2>한 주</h2><p class="pay-net" data-week-net></p><p class="pay-gross">세전 <span data-week-gross></span></p></div>
<div class="pay-period"><h2>한 달</h2><p class="pay-net" data-month-net></p><p class="pay-gross">세전 <span data-month-gross></span></p></div>
<p class="pay-basis" data-basis></p>
<p class="pay-warn" data-under60 hidden>한 달 60시간 미만이면 보통 4대보험 가입 대상이 아니라서 소득세만 떼는 경우가 많아요.</p>
<details class="pay-detail"><summary>무엇을 얼마나 떼는지 보기</summary>
<ul class="pay-lines" data-formula></ul>
<p class="fine" data-contract-note></p></details>
</section>
<section class="pay-notes"><h2>알아 두면 좋아요</h2>
<ul>
<li><strong>주휴수당</strong>은 계산에 넣지 않았어요. 근로자로 주 15시간 이상 일하면 받을 수 있어요.</li>
<li>하루짜리 특강처럼 일회성 강의료는 <strong>기타소득(8.8%)</strong>으로 처리되기도 해요.</li>
<li>방학처럼 수업이 없는 달은 수입이 없을 수 있어요. 계약서의 지급 기준을 꼭 확인하세요.</li>
<li>보험료율은 2026년 기준이에요(국민연금 9.5%, 건강보험 7.19%, 장기요양 건강보험료의 13.14%, 고용보험 0.9%). 근로자가 내는 몫(절반)만 계산했어요.</li>
</ul></section>
</main>
<script src="assets/pay.js?v=""" + asset_version("pay.js") + """" defer></script>"""
    head = f'<link rel="stylesheet" href="assets/pay.css?v={asset_version("pay.css")}">'
    return page(f"강사료 실수령 계산기 · {SITE_NAME}", "한국어 강사 강사료의 한 달 실수령액을 프리랜서(3.3%)와 4대보험 근로자로 비교해 보세요.",
                body, root="", config=config, canonical=absolute(config, "pay.html"), active="pay", extra_head=head)


def absolute(config: dict, path: str) -> str | None:
    base = config.get("site_url")
    return f"{base.rstrip('/')}/{path}" if base else None


def render_sitemap(jobs: list[dict], config: dict, today: dt.date) -> str | None:
    if not config.get("site_url"):
        return None
    service_pages = ["resume.html", "demo.html"] if services_on(config) else []
    urls = ["index.html", "pay.html"] + service_pages + [job["path"] for job in jobs]
    entries = "".join(f"<url><loc>{e(absolute(config, u))}</loc><lastmod>{today.isoformat()}</lastmod></url>" for u in urls)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>\n'


def render_robots(config: dict) -> str:
    sitemap = absolute(config, "sitemap.xml")
    return "User-agent: *\nAllow: /\nDisallow: /test/\n" + (f"Sitemap: {sitemap}\n" if sitemap else "")


# --- build -------------------------------------------------------------------

def build(db_path: Path, out_dir: Path, config: dict, today: dt.date, built_at: dt.datetime,
          approved_only: bool = False) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        jobs = load_jobs(conn, today, approved_only, include_overseas=bool(config.get("private")))
        last_run = conn.execute("SELECT MAX(finished_at) FROM collection_runs").fetchone()[0]
        orgs = review_orgs(conn) if config.get("test") else []
    finally:
        conn.close()
    # "새로 모았어요" reports the last finished collection, not when the HTML was written.
    collected_at = dt.datetime.fromisoformat(last_run).astimezone(KST) if last_run else built_at

    # Rebuild from scratch so expired job pages disappear.
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "jobs").mkdir(parents=True)
    shutil.copytree(STATIC_DIR, out_dir / "assets")
    if config.get("test"):
        shutil.copytree(TEST_STATIC_DIR, out_dir / "assets", dirs_exist_ok=True)

    write = lambda rel, text: (out_dir / rel).write_text(text, encoding="utf-8")
    write("index.html", render_index(jobs, config, collected_at))
    write("pay.html", render_pay(config))
    if services_on(config):
        write("demo.html", render_demo(config))
        write("resume.html", render_resume(config))
    if config.get("test"):
        write("rating.html", render_rating(config, orgs))
        write("review.html", render_review(config, orgs))
    files_dir = Path(config.get("files_dir") or collect_jobs.DEFAULT_FILES_DIR)
    for job in jobs:
        job["files"] = [(name, rel) for name, rel in job["files"] if (files_dir / rel).is_file()]
        for _, rel in job["files"]:
            (out_dir / "files" / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(files_dir / rel, out_dir / "files" / rel)
        write(job["path"], render_job(job, jobs, config, today))
    if config.get("private") or config.get("test"):
        write("robots.txt", "User-agent: *\nDisallow: /\n")
    else:
        sitemap = render_sitemap(jobs, config, today)
        if sitemap:
            write("sitemap.xml", sitemap)
        write("robots.txt", render_robots(config))
    return {
        "jobs": len(jobs),
        "domestic": sum(1 for j in jobs if j["scope"] == "domestic"),
        "overseas": sum(1 for j in jobs if j["scope"] == "overseas"),
        "online": sum(1 for j in jobs if j["scope"] == "online"),
        "on_map": sum(1 for j in jobs if j["has_place"]),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the public job board as static HTML.")
    parser.add_argument("--db", default=str(collect_jobs.DEFAULT_DB), help="SQLite database path")
    parser.add_argument("--out", default=None, help="Output folder (replaced on every build); default site/ or site_private/")
    parser.add_argument(
        "--private",
        action="store_true",
        help="Owner-only build with overseas jobs, marked noindex, written to site_private/ (never deploy it)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Admin-only staging build (larger type, 근무 후기) written to site_test/; serve.py serves it at /test/",
    )
    parser.add_argument(
        "--ad-slots",
        action="store_true",
        help="Draw dashed boxes where ads would go (layout review only; no ads run yet)",
    )
    parser.add_argument(
        "--with-services",
        action="store_true",
        help="Publish the not-yet-launched services (이력서·자소서 첨삭, 시강 교안 AI) on the public site",
    )
    parser.add_argument("--secrets", default=str(collect_jobs.DEFAULT_SECRETS_FILE), help="KEY=value file")
    parser.add_argument("--approved-only", action="store_true", help="Publish only jobs a reviewer approved")
    parser.add_argument("--today", default=None, help="Reference date, YYYY-MM-DD")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.test and args.private:
        parser.error("--test and --private are separate builds; pick one")
    collect_jobs.load_secrets_file(Path(args.secrets))
    now = dt.datetime.now(KST)
    today = dt.date.fromisoformat(args.today) if args.today else now.date()
    config = {
        "site_url": os.environ.get("SITE_URL"),
        "kakao_js_key": os.environ.get("KAKAO_JS_KEY"),
        "alert_endpoint": os.environ.get("ALERT_ENDPOINT"),
        "adsense_client": None if args.private else os.environ.get("ADSENSE_CLIENT"),
        "private": args.private,
        "test": args.test,
        "services": args.with_services,
        "ad_slots": args.ad_slots,
    }
    out = Path(args.out) if args.out else (PRIVATE_OUT if args.private else TEST_OUT if args.test else DEFAULT_OUT)
    # The DB is collected data, not in git: a fresh checkout has none.
    if not Path(args.db).is_file():
        print(f"error: no database at {Path(args.db).resolve()}\n"
              "  Run python collect_jobs.py first, or copy jobs.sqlite3 (and files/) from the machine that collected.",
              file=sys.stderr)
        return 1
    stats = build(Path(args.db), out, config, today, now, args.approved_only)
    print(" ".join(f"{k}={v}" for k, v in stats.items()) + f" out={out.resolve()}")
    if not config["site_url"]:
        print("note: SITE_URL is not set, so canonical links and sitemap.xml were skipped", file=sys.stderr)
    if not config["kakao_js_key"]:
        print("note: KAKAO_JS_KEY is not set, so the map shows a notice instead", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
