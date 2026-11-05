#!/usr/bin/env python3
"""Net visitors from Cloudflare traffic: people, minus the owner, bots and attacks.

Cloudflare's own "visits" count every page request from outside, so search,
AdSense and scraper bots swamp the handful of real readers. This pulls the
last 7 days of per-request groups from the Cloudflare GraphQL API and keeps
only what looks like a person reading the site:

  owner    IPs that opened /test or /admin with the password in the last 30
           days, plus the Android devices (UA with a build id) used from them
  cf       /cdn-cgi/* (Web Analytics beacons, Bot Fight Mode checks)
  attack   any IP that probed wp-/.php/.env/.git, odd ports, or /test,/admin
           without the password: all of its requests go
  bot      bot user agents and verified bots; IPs that only fetch HTML (no
           CSS/JS, no beacon); bulk readers; cloud data centres; fake UAs;
           foreign IPs that never sent a beacon
  human    the rest that opened at least one page

A visitor is one IP, so a phone that changes IP counts more than once.

  python traffic_report.py           # 1 / 3 / 7 day net visitors
  python traffic_report.py --json    # the same as JSON

Needs CLOUDFLARE_API_TOKEN (Zone Analytics: Read) in secrets.env.
/admin in serve.py shows the same report.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_SECRETS = ROOT / "secrets.env"
API = "https://api.cloudflare.com/client/v4"
KST = dt.timezone(dt.timedelta(hours=9))
WINDOWS = (1, 3, 7)
HOST = "korean-job-helper.com"
ADMIN_PATHS = ("/test", "/admin")

PROBE = re.compile(
    r"wp-|wordpress|xmlrpc|wlwmanifest|\.php|\.env|\.git|phpmyadmin|cgi-bin|\.aws|\.ds_store|config\.|"
    r"/backup|\.sql|\.zip|\.bak|actuator|/vendor|/owa|/boaform|/hnap|/solr|/druid|\.asp|/shell|/setup|/api/v1",
    re.I,
)
BOT_UA = re.compile(
    r"bot|crawl|spider|slurp|curl|wget|python|go-http|java/|okhttp|headless|scrapy|httpclient|libwww|axios|"
    r"node-fetch|mediapartners|facebookexternalhit|preview|scan|monitor|lighthouse|audit|^mozilla/5\.0$|^$",
    re.I,
)
# Browsers too old to be real today, or headless/server builds dressed up as one.
FAKE_UA = re.compile(
    r"HeadlessChrome|Linux aarch64|Trident|Android [1-9][;.) ]|iPhone OS 18_7_8|iPhone OS 14_0 |"
    r"Chrome/([1-9]\d|1[01]\d)\.|Firefox/([1-9]\d|10\d)\.|nameserver|validator",
    re.I,
)
# Cloud and hosting ranges seen sending fake browser traffic (AWS, Google Cloud,
# Azure, OVH, Hetzner, Scaleway, M247, DigitalOcean ...).
DATACENTER = re.compile(
    r"^(3\.|13\.|18\.|23\.27\.|23\.81\.|34\.|35\.|44\.|52\.|54\.|104\.197\.|205\.169\.39\.|149\.57\.180\.|"
    r"154\.6\.|192\.144\.|207\.58\.|54\.37\.|51\.|151\.115\.|163\.172\.|88\.99\.|176\.9\.|146\.70\.|209\.20\.|"
    r"144\.31\.|106\.75\.|2001:41d0|2001:bc8|2a01:4f8|2606:e280)"
)
MOBILE = re.compile(r"Mobile|iPhone|Android|iPad")

GROUPS_QUERY = """query($z:String!,$f:ZoneHttpRequestsAdaptiveGroupsFilter_InputObject!){viewer{zones(filter:{zoneTag:$z}){
 httpRequestsAdaptiveGroups(limit:10000, filter:$f){ count dimensions{
  datetimeHour clientIP clientCountryName clientRequestPath clientRequestHTTPHost clientRequestHTTPMethodName
  userAgent edgeResponseStatus verifiedBotCategory requestSource securityAction } } }}}"""
OWNER_QUERY = """query($z:String!,$f:ZoneHttpRequestsAdaptiveGroupsFilter_InputObject!){viewer{zones(filter:{zoneTag:$z}){
 httpRequestsAdaptiveGroups(limit:10000, filter:$f){ count dimensions{ clientIP userAgent } } }}}"""
PAGE_LIMIT = 10000


class TrafficError(RuntimeError):
    pass


# --- Cloudflare ---------------------------------------------------------------

def load_settings(secrets: Path) -> dict[str, str]:
    keys = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ZONE_ID")
    values = {k: os.environ[k] for k in keys if os.environ.get(k)}
    if secrets.is_file():
        for line in secrets.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key.strip() in keys:
                values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    if not values.get("CLOUDFLARE_API_TOKEN"):
        raise TrafficError("secrets.env에 CLOUDFLARE_API_TOKEN이 없어요")
    return values


class Cloudflare:
    def __init__(self, token: str, zone: str | None = None):
        self.token = token
        self.zone = zone or self.find_zone()

    def call(self, url: str, payload: dict | None = None) -> dict:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return json.load(res)
        except OSError as err:
            raise TrafficError(f"Cloudflare에 연결하지 못했어요: {err}") from err

    def find_zone(self) -> str:
        data = self.call(f"{API}/zones?name={HOST}")
        zones = data.get("result") or []
        if not data.get("success") or not zones:
            raise TrafficError(f"Cloudflare에서 {HOST} 영역을 찾지 못했어요: {data.get('errors')}")
        return zones[0]["id"]

    def groups(self, query: str, start: dt.datetime, end: dt.datetime, extra: dict | None = None) -> list[dict]:
        """All request groups in [start, end); halves the span when a page is full."""
        stamp = lambda t: t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        filt = {"datetime_geq": stamp(start), "datetime_lt": stamp(end), **(extra or {})}
        data = self.call(f"{API}/graphql", {"query": query, "variables": {"z": self.zone, "f": filt}})
        if data.get("errors"):
            raise TrafficError(f"Cloudflare 응답 오류: {data['errors'][0].get('message')}")
        rows = data["data"]["viewer"]["zones"][0]["httpRequestsAdaptiveGroups"]
        if len(rows) >= PAGE_LIMIT and end - start > dt.timedelta(minutes=10):
            mid = start + (end - start) / 2
            return self.groups(query, start, mid, extra) + self.groups(query, mid, end, extra)
        return rows

    def requests(self, start: dt.datetime, end: dt.datetime) -> list[dict]:
        rows, t = [], start
        while t < end:
            step = min(t + dt.timedelta(hours=12), end)
            rows += self.groups(GROUPS_QUERY, t, step)
            t = step
        return rows

    def owner_rows(self, end: dt.datetime) -> list[dict]:
        """Who opened an admin page with the password in the last 30 days, and every
        device UA those IPs used (the owner's phone may never open /test itself)."""
        start = end - dt.timedelta(days=30)
        extra = {"edgeResponseStatus": 200,
                 "OR": [{"clientRequestPath_like": p + "%"} for p in ADMIN_PATHS]}
        admin = self.groups(OWNER_QUERY, start, end, extra)
        ips = sorted({r["dimensions"]["clientIP"] for r in admin})
        if not ips:
            return admin
        return admin + self.groups(OWNER_QUERY, start, end, {"clientIP_in": ips, "userAgent_like": "% Build/%"})


# --- classification -------------------------------------------------------------

def owner_markers(owner_rows: list[dict]) -> tuple[set[str], set[str]]:
    # Every row comes from an owner IP: admin pages, or device UAs seen on those IPs.
    ips = {r["dimensions"]["clientIP"] for r in owner_rows}
    # Only UAs that name the device build; generic ones are shared by millions.
    devices = {r["dimensions"]["userAgent"] for r in owner_rows if " Build/" in r["dimensions"]["userAgent"]}
    return ips, devices


def is_admin_path(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in ADMIN_PATHS)


def is_page(d: dict) -> bool:
    path = d["clientRequestPath"]
    return (d["edgeResponseStatus"] in (200, 304) and d["clientRequestHTTPMethodName"] in ("GET", "")
            and d.get("securityAction", "unknown") in ("unknown", "")
            and (path.endswith(".html") or path.endswith("/")) and not is_admin_path(path))


def kst_date(d: dict) -> str:
    hour = dt.datetime.fromisoformat(d["datetimeHour"].replace("Z", "+00:00"))
    return hour.astimezone(KST).date().isoformat()


def classify(rows: list[dict], owner_ips: set[str], owner_devices: set[str]) -> dict[str, dict]:
    """Per IP: its verdict and the pages it opened (by KST day)."""
    attackers = set()
    for r in rows:
        d = r["dimensions"]
        if d["clientIP"] in owner_ips:
            continue
        if (PROBE.search(d["clientRequestPath"]) or d["clientRequestHTTPHost"] != HOST
                or is_admin_path(d["clientRequestPath"]) or d.get("securityAction") == "block"
                # Bot Fight Mode checks run inside real browsers: those are fine.
                or d.get("requestSource", "eyeball") not in ("eyeball", "inBrowserChallenge")):
            attackers.add(d["clientIP"])

    ips: dict[str, dict] = collections.defaultdict(lambda: {
        "country": "", "ua": set(), "assets": 0, "beacons": 0, "flag": None,
        "pages": collections.Counter(), "days": collections.Counter(), "bot_days": collections.Counter(),
        "page_hits": 0, "verdict": ""})
    for r in rows:
        d, n = r["dimensions"], r["count"]
        ip, path = d["clientIP"], d["clientRequestPath"]
        info = ips[ip]
        info["country"] = d["clientCountryName"]
        info["ua"].add(d["userAgent"])
        if path == "/cdn-cgi/rum":
            info["beacons"] += n
            continue
        if path.startswith("/cdn-cgi/"):
            continue
        if ip in owner_ips:
            info["flag"] = "owner"
        elif ip in attackers:
            info["flag"] = "attack"
        elif d["verifiedBotCategory"] or BOT_UA.search(d["userAgent"]):
            # A bot UA on an IP marks only that request; a person may share the IP.
            if is_page(d):
                info["bot_days"][kst_date(d)] += n
            continue
        if path.startswith("/assets/"):
            info["assets"] += n
        if is_page(d):
            info["page_hits"] += n
            info["pages"][path] += n
            info["days"][kst_date(d)] += n

    for ip, info in ips.items():
        info["verdict"] = verdict(ip, info, owner_devices)
    return ips


def verdict(ip: str, info: dict, owner_devices: set[str]) -> str:
    if info["flag"]:
        return info["flag"]
    if not info["page_hits"]:
        return "none"
    if info["ua"] & owner_devices:
        return "owner"
    if not info["beacons"] and (not info["assets"] or len(info["pages"]) >= 15):
        return "bot"  # HTML only, or a whole-site sweep
    if DATACENTER.search(ip) or all(FAKE_UA.search(u) for u in info["ua"]):
        return "bot"
    if not info["beacons"] and info["country"] != "KR":
        return "bot"
    return "human"


# --- report ---------------------------------------------------------------------

def summarize(ips: dict[str, dict], today: dt.date) -> dict:
    days = [(today - dt.timedelta(days=i)).isoformat() for i in range(max(WINDOWS) - 1, -1, -1)]
    windows = []
    for n in WINDOWS:
        span = set(days[-n:])
        noise = collections.Counter()
        visitors, views = 0, 0
        countries, pages, devices = collections.Counter(), collections.Counter(), collections.Counter()
        for info in ips.values():
            hits = sum(c for day, c in info["days"].items() if day in span)
            noise["bot"] += sum(c for day, c in info["bot_days"].items() if day in span)
            if info["verdict"] != "human":
                noise[info["verdict"]] += hits
                continue
            if not hits:
                continue
            visitors += 1
            views += hits
            countries[info["country"]] += 1
            devices["모바일" if any(MOBILE.search(u) for u in info["ua"]) else "PC"] += 1
            if n == max(WINDOWS):
                for path, c in info["pages"].items():
                    pages[page_label(path)] += c
        windows.append({"days": n, "from": days[-n], "visitors": visitors, "pageviews": views,
                        "countries": countries.most_common(8), "devices": dict(devices),
                        "noise": {k: noise[k] for k in ("owner", "bot", "attack")}})
    daily = []
    for day in days:
        humans = [i for i in ips.values() if i["verdict"] == "human" and i["days"].get(day)]
        daily.append({"date": day, "visitors": len(humans), "pageviews": sum(i["days"][day] for i in humans)})
    top = collections.Counter()
    for info in ips.values():
        if info["verdict"] == "human":
            for path, c in info["pages"].items():
                top[page_label(path)] += c
    return {"today": today.isoformat(), "windows": windows, "daily": daily, "pages": top.most_common(10)}


def page_label(path: str) -> str:
    if path in ("/", "/index.html"):
        return "첫 화면"
    if path.startswith("/jobs/"):
        return "공고 상세"
    return path.lstrip("/")


def build_report(secrets: Path = DEFAULT_SECRETS, now: dt.datetime | None = None) -> dict:
    settings = load_settings(secrets)
    cf = Cloudflare(settings["CLOUDFLARE_API_TOKEN"], settings.get("CLOUDFLARE_ZONE_ID"))
    now = now or dt.datetime.now(KST)
    today = now.astimezone(KST).date()
    start = dt.datetime.combine(today - dt.timedelta(days=max(WINDOWS) - 1), dt.time(), KST)
    owner_ips, owner_devices = owner_markers(cf.owner_rows(now))
    report = summarize(classify(cf.requests(start, now), owner_ips, owner_devices), today)
    report["generated_at"] = now.astimezone(KST).strftime("%Y-%m-%d %H:%M")
    return report


def render_text(report: dict) -> str:
    lines = [f"순방문자 (대표님·봇·해킹 탐색 제외, {report['generated_at']} KST 기준)", ""]
    for w in report["windows"]:
        label = "오늘" if w["days"] == 1 else f"최근 {w['days']}일"
        noise = w["noise"]
        lines.append(f"{label:7} 방문자 {w['visitors']:4}명  페이지뷰 {w['pageviews']:5}회   "
                     f"(제외 페이지뷰: 봇 {noise['bot']}, 해킹 {noise['attack']}, 대표님 {noise['owner']})")
    lines += ["", "날짜        방문자  페이지뷰"]
    lines += [f"{d['date']}  {d['visitors']:5}  {d['pageviews']:7}" for d in report["daily"]]
    lines += ["", "7일 국가: " + ", ".join(f"{c} {n}" for c, n in report["windows"][-1]["countries"]),
              "7일 페이지: " + ", ".join(f"{p} {n}" for p, n in report["pages"])]
    return "\n".join(lines)


def render_html(report: dict | None, error: str | None = None) -> str:
    e = lambda s: html.escape(str(s))
    body = []
    if error:
        body.append(f'<p class="error">{e(error)}</p>')
    if report:
        cards = "".join(
            f'<div class="card"><h2>{"오늘" if w["days"] == 1 else f"최근 {w["days"]}일"}</h2>'
            f'<p class="big">{w["visitors"]}<span>명</span></p><p>페이지뷰 {w["pageviews"]}회</p>'
            f'<p class="muted">{e(w["from"])} ~ 오늘</p></div>'
            for w in report["windows"])
        noise = "".join(
            f'<tr><th>{"오늘" if w["days"] == 1 else f"{w["days"]}일"}</th><td>{w["pageviews"]}</td>'
            f'<td>{w["noise"]["bot"]}</td><td>{w["noise"]["attack"]}</td><td>{w["noise"]["owner"]}</td></tr>'
            for w in report["windows"])
        daily = "".join(f'<tr><th>{e(d["date"])}</th><td>{d["visitors"]}</td><td>{d["pageviews"]}</td></tr>'
                        for d in reversed(report["daily"]))
        week = report["windows"][-1]
        countries = ", ".join(f"{e(c)} {n}" for c, n in week["countries"]) or "-"
        devices = ", ".join(f"{e(k)} {v}" for k, v in week["devices"].items()) or "-"
        pages = ", ".join(f"{e(p)} {n}" for p, n in report["pages"]) or "-"
        body.append(
            f'<div class="cards">{cards}</div>'
            f'<h2>날짜별</h2><table><tr><th>날짜</th><th>방문자</th><th>페이지뷰</th></tr>{daily}</table>'
            f'<h2>뺀 페이지뷰</h2><table><tr><th></th><th>사람</th><th>봇</th><th>해킹 탐색</th><th>대표님</th></tr>{noise}</table>'
            f'<h2>최근 7일 방문자</h2><p>국가: {countries}</p><p>기기: {devices}</p><p>페이지: {pages}</p>'
            f'<p class="muted">{e(report["generated_at"])} KST 기준 · 10분마다 새로 계산해요 · '
            f'방문자는 IP 기준이라 휴대폰은 한 사람이 여러 명으로 잡힐 수 있어요</p>')
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>순방문자</title>
<style>
:root{{--bg:#fff;--fg:#1d1d1f;--muted:#6e6e73;--line:#e5e5ea;--card:#f5f5f7;--accent:#0a64d6;--err:#b3261e}}
@media (prefers-color-scheme: dark){{:root{{--bg:#111;--fg:#f2f2f2;--muted:#a1a1a6;--line:#333;--card:#1c1c1e;--accent:#6aa8ff;--err:#ff8a80}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}}
main{{max-width:760px;margin:0 auto;padding:24px 16px 48px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:28px 0 8px}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}
.card{{background:var(--card);border-radius:12px;padding:14px}} .card h2{{margin:0;font-size:14px;color:var(--muted)}}
.card p{{margin:2px 0}} .big{{font-size:32px;font-weight:700;color:var(--accent)}} .big span{{font-size:15px;margin-left:2px}}
table{{border-collapse:collapse;width:100%}} th,td{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right}}
th:first-child{{text-align:left}} .muted{{color:var(--muted);font-size:13px}} .error{{color:var(--err)}}
@media (max-width:480px){{.cards{{grid-template-columns:1fr}}}}
</style></head><body><main><h1>순방문자</h1>
<p class="muted">대표님 접속 · 검색·광고·AI 봇 · 해킹 탐색 · Cloudflare 비콘을 뺀 값이에요</p>
{''.join(body)}</main></body></html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Net visitors for the last 1 / 3 / 7 days from Cloudflare")
    parser.add_argument("--secrets", default=str(DEFAULT_SECRETS), help="KEY=value file with CLOUDFLARE_API_TOKEN")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a table")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        report = build_report(Path(args.secrets))
    except TrafficError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=1) if args.json else render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
