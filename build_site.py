#!/usr/bin/env python3
"""Build the public job board as static HTML from the collector's SQLite DB.

    python build_site.py                      # writes site/
    python -m http.server -d site 8000        # preview at http://localhost:8000

Every value from a collected posting is untrusted text from another site: it is
HTML-escaped on the way out, and only http(s) links are ever linked.
"""

from __future__ import annotations

import argparse
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

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "site_static"
DEFAULT_OUT = ROOT / "site"
# Owner-only build that also shows overseas jobs. Gitignored; never deploy it.
PRIVATE_OUT = ROOT / "site_private"
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
        return "마감일 원문 확인", ""
    if days == 0:
        return "오늘 마감", "urgent"
    if days <= 7:
        return f"마감 D-{days}", "urgent"
    return f"D-{days}", ""


def deadline_text(deadline: str | None) -> str:
    if deadline == "rolling":
        return "채용될 때까지"
    if not deadline:
        return "원문에서 확인해 주세요"
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
    job["apply_url"] = safe_url(job.get("original_url"))
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

def page(title: str, description: str, body: str, *, root: str, config: dict, canonical: str | None,
         active: str, extra_head: str = "", body_attrs: str = "") -> str:
    adsense = config.get("adsense_client")
    head_ads = (
        f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={e(adsense)}" crossorigin="anonymous"></script>'
        if adsense else ""
    )
    site_config = {"kakaoKey": config.get("kakao_js_key") or "", "alertEndpoint": config.get("alert_endpoint") or ""}
    private = config.get("private")
    private_head = '<meta name="robots" content="noindex, nofollow">' if private else ""
    private_bar = (
        '<div class="private-bar" role="note">비공개 미리보기 · 해외 공고와 준비 중인 서비스 포함 · 배포하지 마세요</div>'
        if private else ""
    )
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
<link rel="stylesheet" href="{root}assets/styles.css">
{head_ads}
{private_head}
{extra_head}
</head>
<body{body_attrs}>
{private_bar}
{header(root, active, services_on(config))}
{body}
{footer(root)}
<script>window.SITE = {json_for_script(site_config)};</script>
<script src="{root}assets/app.js" defer></script>
</body>
</html>
"""


def services_on(config: dict) -> bool:
    """Paid services (첨삭, 시강 교안 AI) are not launched yet: the public site
    shows only the free job board. --with-services turns them on; the private
    build always shows them so they can be worked on."""
    return bool(config.get("services") or config.get("private"))


def header(root: str, active: str, with_services: bool = False) -> str:
    links = [("jobs", f"{root}index.html", "채용공고")]
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
<a class="btn btn-soft" href="{root}index.html#alert">알림 받기</a>
</div></header>"""


def footer(root: str) -> str:
    return f"""<footer class="foot"><div class="wrap">
<strong>{SITE_NAME}</strong>
<span>직업정보제공사업 신고번호 [신고 후 기재]</span>
<span>공고는 각 기관 원문을 기준으로 정리하며, 지원은 원문에서 해요.</span>
</div></footer>"""


def ad_slot(config: dict, kind: str, label: str) -> str:
    # With AdSense on, Auto ads place units; the reserved boxes are for review
    # only. The owner-only build carries no ads at all.
    if config.get("adsense_client") or config.get("private"):
        return ""
    tag = "li" if kind == "infeed" else "div"
    return f'<{tag} class="ad-slot {kind}" aria-label="광고">{label}</{tag}>'


def job_row(job: dict, root: str) -> str:
    chips = "".join(f'<span class="chip">{e(c)}</span>' for c in job["chips"])
    search = " ".join(str(x) for x in (job.get("title"), job["org"], job["place"], job.get("location_text")) if x).lower()
    lat = job["latitude"] if job["has_place"] else ""
    lng = job["longitude"] if job["has_place"] else ""
    return f"""<li class="job-row" data-id="{job['job_id']}" data-scope="{job['scope']}" data-newcomer="{1 if job.get('newcomer_ok') == 1 else 0}" data-demo="{1 if job.get('demo_lesson') == 1 else 0}" data-lat="{lat}" data-lng="{lng}" data-deadline="{e(job.get('deadline') or '')}" data-title="{e(job.get('title'))}" data-org="{e(job['org'] + ' · ' + job['place'])}" data-search="{e(search)}">
<button type="button" class="pick">
<span class="badge {job['badge_class']}" data-badge="{e(job.get('deadline') or '')}">{e(job['badge'])}</span>
<span class="job-title">{e(job.get('title'))}</span>
<span class="job-org">{e(job['org'])} · {e(job['place'])}</span>
<span class="chips">{chips}</span>
</button>
<a class="go" href="{root}{job['path']}" aria-label="{e(job['org'])} 공고 자세히 보기">›</a>
</li>"""


# --- pages -------------------------------------------------------------------

def render_index(jobs: list[dict], config: dict, collected_at: dt.datetime) -> str:
    counts = {scope: sum(1 for j in jobs if j["scope"] == scope) for scope in ("domestic", "overseas", "online")}
    rows = [job_row(job, "") for job in jobs]
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
<label class="search"><span class="sr-only">기관명이나 지역 검색</span><input type="search" data-search-input placeholder="기관명, 지역으로 찾기"></label>
</div>
</section>

<div class="board">
<section class="map-panel" aria-label="지도">
<div class="map-box" data-view="map">
<div id="map"></div>
<p class="map-note">지도를 불러오는 중이에요</p>
<div class="map-card" hidden>
<div class="grow"><span class="badge"></span><p class="t"></p><p class="o"></p></div>
<a class="btn btn-primary" href="#">자세히 보기</a>
</div>
</div>
{countries_view}
<div class="alt-view" data-view="online" hidden>
<h2>온라인·재택 공고는 장소가 없어요</h2>
<p>오른쪽 목록에서 수업 시간대와 학습자 국가를 확인하세요.</p>
</div>
</section>

<section class="list-panel" aria-labelledby="listTitle">
<div class="panel-head"><h2 id="listTitle">마감 가까운 순</h2><span data-count>{len(jobs)}개</span></div>
<div class="empty" data-empty hidden><p>조건에 맞는 공고가 아직 없어요</p><p>알림을 켜 두면 올라오는 대로 알려 드려요.</p></div>
<ul class="jobs">{"".join(rows)}</ul>
</section>
</div>

<div class="row">
<section id="alert" class="callout alert-box" aria-labelledby="alertTitle">
<h2 id="alertTitle">지금 고른 조건 그대로<br>새 공고를 알려 드릴게요</h2>
<p class="desc"><span data-filter-summary>전체</span> · 새 공고와 마감 3일 전에만, 일주일에 두 번 이하로 보내요.</p>
<form class="alert-form" data-alert-form>
<label><span class="sr-only">이메일</span><input type="email" name="email" required placeholder="이메일 주소" autocomplete="email"></label>
<button type="submit" class="btn btn-primary">알림 받기</button>
</form>
<p class="alert-done" data-alert-done role="status" hidden></p>
</section>
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
        ("전형", "서류 → 모의수업" if job.get("demo_lesson") == 1 else None),
        ("강의료", job.get("salary_text")),
        ("지원 사항", job.get("benefits")),
    ]
    fact_rows = "".join(f"<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>" for k, v in facts if v)
    chips = "".join(f'<span class="chip">{e(c)}</span>' for c in job["chips"])

    map_section = ""
    if job["has_place"]:
        map_section = f"""<section class="sec" aria-labelledby="mapTitle">
<h2 id="mapTitle">어디서 일하나요</h2>
<p class="fine">{e(job.get('address') or job['place'])}</p>
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

    apply_link = (
        f'<a class="btn btn-primary btn-lg" href="{e(job["apply_url"])}" target="_blank" rel="noopener nofollow">원문 공고 열기</a>'
        if job["apply_url"] else '<span class="fine">원문 링크를 확인하지 못했어요.</span>'
    )
    collected = (job.get("collected_at") or "")[:10].replace("-", ".")
    mentoring = SERVICE_LINKS["mentoring"]
    # After "지원했어요": with services, prepare for the demo lesson; without,
    # keep the person coming back with the free job alert.
    if services_on(config):
        applied_text = "모의수업 연락이 오기 전에 교안을 미리 준비해 두세요."
        applied_link = (
            f'<a class="btn btn-dark" href="{e(mentoring)}">리허설 일정 보기</a>' if mentoring
            else f'<a class="btn btn-dark" href="{root}demo.html">교안 준비하기</a>'
        )
    else:
        applied_text = "다른 공고도 놓치지 않게 새 공고 알림을 켜 두세요."
        applied_link = f'<a class="btn btn-dark" href="{root}index.html#alert">알림 받기</a>'

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
    side = [alert_block, near_block]
    if mentoring and services_on(config):
        side.insert(0, f"""<section class="callout" aria-labelledby="mentorTitle"><p class="kicker">1:1 커리어 멘토링</p>
<h2 id="mentorTitle">면접 날짜가 잡혔다면<br>시강 리허설부터</h2>
<p class="desc">현직 강사가 교안과 시연을 보고 고칠 점을 짚어 드려요.</p>
<a class="btn btn-dark" href="{e(mentoring)}">일정 고르기</a></section>""")
    side.append(service_blocks(config, root))

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
<section class="sec" aria-labelledby="sumTitle"><h2 id="sumTitle">이런 공고예요</h2>
<p class="prose">{e(job.get('summary') or '원문에서 자세한 내용을 확인해 주세요.')}</p>
<p class="fine">원문을 바탕으로 정리했어요. 근무 일정과 제출 서류는 원문에서 확인하세요.</p></section>
{steps}
{demo_cta}
<section class="sec" aria-labelledby="applyTitle"><h2 id="applyTitle">지원은 원문에서 해요</h2>
<p class="fine">지원서 양식과 제출처가 기관 원문에 있어요.</p>
<div class="apply-row">{apply_link}
<button type="button" class="btn btn-gray btn-lg" data-applied>지원했어요</button>
<button type="button" class="btn btn-gray btn-lg" data-save aria-pressed="false">저장</button></div>
<div class="applied-note" data-applied-note role="status" hidden><p><strong>지원 완료, 수고했어요.</strong> {applied_text}</p>
{applied_link}</div>
<p class="fine">출처 {e(job.get('source_name'))} · {e(collected)} 수집</p></section>
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
    posted = (job.get("posted_at") or job.get("first_seen_at") or "")[:10]
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
<div><h1 id="demoHead" class="title-xl" style="font-size: clamp(28px, 3.4vw, 34px)">모의수업 교안,<br>초안부터 같이 잡아 볼게요</h1>
<p class="fine" style="font-size: 15px">가입 없이 3번까지 무료예요.</p></div>
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


def absolute(config: dict, path: str) -> str | None:
    base = config.get("site_url")
    return f"{base.rstrip('/')}/{path}" if base else None


def render_sitemap(jobs: list[dict], config: dict, today: dt.date) -> str | None:
    if not config.get("site_url"):
        return None
    service_pages = ["resume.html", "demo.html"] if services_on(config) else []
    urls = ["index.html"] + service_pages + [job["path"] for job in jobs]
    entries = "".join(f"<url><loc>{e(absolute(config, u))}</loc><lastmod>{today.isoformat()}</lastmod></url>" for u in urls)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>\n'


def render_robots(config: dict) -> str:
    sitemap = absolute(config, "sitemap.xml")
    return "User-agent: *\nAllow: /\n" + (f"Sitemap: {sitemap}\n" if sitemap else "")


# --- build -------------------------------------------------------------------

def build(db_path: Path, out_dir: Path, config: dict, today: dt.date, built_at: dt.datetime,
          approved_only: bool = False) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        jobs = load_jobs(conn, today, approved_only, include_overseas=bool(config.get("private")))
        last_run = conn.execute("SELECT MAX(finished_at) FROM collection_runs").fetchone()[0]
    finally:
        conn.close()
    # "새로 모았어요" reports the last finished collection, not when the HTML was written.
    collected_at = dt.datetime.fromisoformat(last_run).astimezone(KST) if last_run else built_at

    # Rebuild from scratch so expired job pages disappear.
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "jobs").mkdir(parents=True)
    shutil.copytree(STATIC_DIR, out_dir / "assets")

    write = lambda rel, text: (out_dir / rel).write_text(text, encoding="utf-8")
    write("index.html", render_index(jobs, config, collected_at))
    if services_on(config):
        write("demo.html", render_demo(config))
        write("resume.html", render_resume(config))
    for job in jobs:
        write(job["path"], render_job(job, jobs, config, today))
    if config.get("private"):
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
        "--with-services",
        action="store_true",
        help="Publish the not-yet-launched services (이력서·자소서 첨삭, 시강 교안 AI) on the public site",
    )
    parser.add_argument("--secrets", default=str(collect_jobs.DEFAULT_SECRETS_FILE), help="KEY=value file")
    parser.add_argument("--approved-only", action="store_true", help="Publish only jobs a reviewer approved")
    parser.add_argument("--today", default=None, help="Reference date, YYYY-MM-DD")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    collect_jobs.load_secrets_file(Path(args.secrets))
    now = dt.datetime.now(KST)
    today = dt.date.fromisoformat(args.today) if args.today else now.date()
    config = {
        "site_url": os.environ.get("SITE_URL"),
        "kakao_js_key": os.environ.get("KAKAO_JS_KEY"),
        "alert_endpoint": os.environ.get("ALERT_ENDPOINT"),
        "adsense_client": None if args.private else os.environ.get("ADSENSE_CLIENT"),
        "private": args.private,
        "services": args.with_services,
    }
    out = Path(args.out) if args.out else (PRIVATE_OUT if args.private else DEFAULT_OUT)
    stats = build(Path(args.db), out, config, today, now, args.approved_only)
    print(" ".join(f"{k}={v}" for k, v in stats.items()) + f" out={out.resolve()}")
    if not config["site_url"]:
        print("note: SITE_URL is not set, so canonical links and sitemap.xml were skipped", file=sys.stderr)
    if not config["kakao_js_key"]:
        print("note: KAKAO_JS_KEY is not set, so the map shows a notice instead", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
