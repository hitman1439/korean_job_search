#!/usr/bin/env python3
"""Pull structured facts (qualification, experience, salary, demo lesson, ...) out
of a collected posting.

Two layers:
- extract_rules(): regular expressions, free, always run.
- Claude, opt-in with --llm-fields: fills what the rules miss and writes a
  summary in our own words so the public site never republishes the original
  notice text. Two backends:
    claude-code  the local `claude` CLI in headless mode, on the signed-in
                 Claude Code account (no API key)
    api          the Anthropic SDK with ANTHROPIC_API_KEY
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Callable

LLM_MODEL = "claude-opus-5-5"

INSTITUTION_TYPES = [
    "university",          # 국내 대학 어학당·언어교육원·국제교육원
    "overseas_university", # 해외 대학
    "sejong",              # 세종학당
    "multicultural",       # 가족센터·다문화가족지원센터
    "kiip",                # 사회통합프로그램
    "school",              # 초중고·교육청·유치원
    "academy",             # 사설 학원·어학원
    "online",              # 온라인·화상·재택
    "government",          # 공공기관·재단
    "other",
]

DOMESTIC_REGIONS = {
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원",
    "충북", "충남", "전북", "전남", "경북", "경남", "제주",
}

ENGLISH_COUNTRIES = {
    "united states": "미국", "usa": "미국", "u.s.": "미국", "canada": "캐나다", "japan": "일본",
    "china": "중국", "taiwan": "대만", "vietnam": "베트남", "thailand": "태국",
    "indonesia": "인도네시아", "philippines": "필리핀", "mongolia": "몽골",
    "uzbekistan": "우즈베키스탄", "kazakhstan": "카자흐스탄", "united kingdom": "영국",
    "germany": "독일", "france": "프랑스", "australia": "호주", "new zealand": "뉴질랜드",
}


# Country names that may stand in for a location on overseas postings. The
# collector imports this too, so both agree on what counts as a country.
COUNTRY_NAMES = {
    "미국", "캐나다", "멕시코", "브라질", "아르헨티나", "칠레", "콜롬비아", "페루",
    "영국", "독일", "프랑스", "스페인", "이탈리아", "네덜란드", "벨기에", "스위스", "오스트리아",
    "폴란드", "체코", "헝가리", "루마니아", "불가리아", "튀르키예", "터키", "러시아", "우크라이나",
    "스웨덴", "노르웨이", "덴마크", "핀란드", "포르투갈", "그리스",
    "일본", "중국", "대만", "홍콩", "마카오", "몽골", "베트남", "태국", "인도네시아", "필리핀",
    "말레이시아", "싱가포르", "캄보디아", "라오스", "미얀마", "인도", "네팔", "스리랑카", "방글라데시",
    "파키스탄", "우즈베키스탄", "카자흐스탄", "키르기스스탄", "타지키스탄", "투르크메니스탄",
    "아제르바이잔", "조지아", "아르메니아", "이집트", "모로코", "케냐", "나이지리아", "남아프리카공화국",
    "사우디아라비아", "아랍에미리트", "UAE", "카타르", "이스라엘", "이란", "호주", "뉴질랜드",
}


def detect_country(title: str, location: str | None, text: str) -> str | None:
    if location in DOMESTIC_REGIONS:
        return "대한민국"
    if location in COUNTRY_NAMES:
        return location
    # Longest first, so "인도네시아" wins over "인도".
    for name in sorted(COUNTRY_NAMES, key=len, reverse=True):
        if name in title:
            return name
    lowered = f"{title} {text[:2000]}".casefold()
    for english, korean in ENGLISH_COUNTRIES.items():
        if re.search(rf"\b{re.escape(english)}\b", lowered):
            return korean
    return None


def detect_institution_type(title: str, institution: str | None, location: str | None, overseas: bool) -> str:
    name = f"{institution or ''} {title}"
    if location in {"온라인", "재택"} or re.search(r"온라인|화상|재택|online", name, re.I):
        return "online"
    if "세종학당" in name:
        return "sejong"
    if re.search(r"가족센터|다문화", name):
        return "multicultural"
    if re.search(r"사회통합\s*프로그램|KIIP|이민자", name, re.I):
        return "kiip"
    if re.search(r"초등학교|중학교|고등학교|교육청|유치원|교육지원청", name):
        return "school"
    if re.search(r"대학교|대학|大学|大學|어학당|언어교육원|국제교육원|한국어교육원|University|College", name, re.I):
        return "overseas_university" if overseas else "university"
    if re.search(r"학원|어학원", name):
        return "academy"
    if re.search(r"재단|진흥원|국립|공단|센터", name):
        return "government"
    return "other"


def detect_qualification(text: str) -> str | None:
    levels = [
        (int(match.group(1)), bool(match.group(2)))
        for match in re.finditer(r"한국어\s*교원\s*(?:자격\s*(?:증)?)?\s*([123])\s*급\s*(이상)?", text)
    ]
    if not levels:
        return None
    # The loosest requirement named is what the applicant actually needs.
    level, or_above = max(levels)
    return f"한국어교원 {level}급{' 이상' if or_above or level > 1 else ''}"


def detect_experience(text: str) -> str | None:
    match = re.search(
        r"(?:강의|교육|교수|강사|한국어\s*교육)?\s*경력\s*(\d+)\s*(년|개월|학기|시간)\s*이상", text
    )
    if match:
        return f"경력 {match.group(1)}{match.group(2)} 이상"
    if re.search(r"경력자\s*(?:우대|우선)", text):
        return "경력자 우대"
    return None


def detect_newcomer_ok(text: str, experience: str | None) -> int | None:
    if re.search(r"신입\s*(?:가능|환영|지원\s*가능)|경력\s*무관|신입\s*[·/,]\s*경력|경력\s*없어도|초보\s*가능", text):
        return 1
    if experience and experience != "경력자 우대":
        return 0
    return None


def detect_demo_lesson(text: str) -> int | None:
    pattern = (
        r"모의\s*수업|모의\s*강의|시범\s*강의|시범\s*수업|시강|수업\s*시연|강의\s*시연"
        r"|teaching\s+demonstration|demo(?:nstration)?\s+(?:lesson|class)|sample\s+lesson"
    )
    return 1 if re.search(pattern, text, re.I) else None


def detect_salary(text: str) -> str | None:
    match = re.search(
        r"(?:강의료|강사료|시간당\s*강의료|시급|급여|보수|월급|연봉|임금)\s*[:：]?\s*"
        r"([^.\n]{0,30}?\d[\d,.]*\s*(?:만\s*)?원(?:\s*\([^)]{0,20}\))?)",
        text,
    )
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()
    english = re.search(r"(?:salary|compensation|pay)[^$\n]{0,40}(\$\s?\d[\d,]*(?:\s*[-–]\s*\$?\s?\d[\d,]*)?)", text, re.I)
    return english.group(1).replace(" ", "") if english else None


def detect_benefits(text: str) -> str | None:
    found = [
        label
        for label, pattern in (
            ("항공권", r"항공권|왕복\s*항공|airfare|flight"),
            ("숙소", r"숙소|주거|기숙사|사택|housing|accommodation"),
            ("비자", r"비자|visa"),
            ("보험", r"4대\s*보험|의료\s*보험|health\s+insurance"),
        )
        if re.search(pattern, text, re.I)
    ]
    return ", ".join(found) or None


def build_summary(job: dict, fields: dict) -> str:
    """A factual one-liner in our own words, used until an LLM summary exists."""
    place = fields.get("country") if fields.get("is_overseas") else job.get("location_text")
    parts = [p for p in (job.get("institution_name"), place) if p]
    head = " · ".join(parts) or "기관 미확인"
    deadline = job.get("deadline")
    tail = "상시 모집" if deadline == "rolling" else (f"{deadline} 마감" if deadline else "마감일 원문 확인")
    facts = [
        fields.get("qualification"),
        fields.get("experience_required"),
        "신입 가능" if fields.get("newcomer_ok") == 1 else None,
        "모의수업 있음" if fields.get("demo_lesson") == 1 else None,
    ]
    detail = ", ".join(f for f in facts if f)
    return f"{head} 한국어 강사 모집, {tail}." + (f" {detail}." if detail else "")


def extract_rules(job: dict) -> dict:
    title = job.get("title") or ""
    text = job.get("raw_text") or job.get("description") or ""
    body = f"{title} {text}"
    location = job.get("location_text")
    country = detect_country(title, location, text)
    overseas = (
        bool(country and country != "대한민국")
        or location in {"해외", "국외"}
        or re.search(r"(?:국외|해외)\s*파견", title) is not None
    )
    experience = detect_experience(body)
    fields = {
        "country": country,
        "is_overseas": 1 if overseas else 0,
        "institution_type": detect_institution_type(title, job.get("institution_name"), location, overseas),
        "qualification": detect_qualification(body),
        "experience_required": experience,
        "newcomer_ok": detect_newcomer_ok(body, experience),
        "demo_lesson": detect_demo_lesson(body),
        "salary_text": detect_salary(body),
        "benefits": detect_benefits(body) if overseas else None,
    }
    fields["summary"] = build_summary(job, fields)
    return fields


# --- Claude ---

def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "institution_type": {"type": "string", "enum": INSTITUTION_TYPES},
        "country": _nullable({"type": "string"}),
        "qualification": _nullable({"type": "string"}),
        "experience_required": _nullable({"type": "string"}),
        "newcomer_ok": _nullable({"type": "boolean"}),
        "demo_lesson": _nullable({"type": "boolean"}),
        "salary_text": _nullable({"type": "string"}),
        "benefits": _nullable({"type": "string"}),
        "summary": {"type": "string"},
    },
    "required": [
        "institution_type", "country", "qualification", "experience_required",
        "newcomer_ok", "demo_lesson", "salary_text", "benefits", "summary",
    ],
    "additionalProperties": False,
}

LLM_SYSTEM = """You read job postings for Korean-language teachers (한국어 강사/한국어교원) and record facts about them for a job board.

The posting text was scraped from a web page, so it may include menus, other listings, or comments; use only the posting itself. Record only what the posting states. Use null when it does not say; do not infer a value from what is typical.

Write every string value in Korean.
- institution_type: university (Korean university language centers), overseas_university, sejong (세종학당), multicultural (가족센터/다문화), kiip (사회통합프로그램), school (K-12, 교육청), academy (private 학원), online, government (public agencies, foundations), other.
- country: the country where the work happens, e.g. "대한민국", "미국"; null for fully online work.
- qualification: the required teaching credential, e.g. "한국어교원 2급 이상".
- experience_required: the required teaching experience, e.g. "강의 경력 1년 이상".
- newcomer_ok: true if applicants without experience may apply, false if experience is required.
- demo_lesson: true if the selection includes a demo lesson (모의수업, 시강, teaching demonstration).
- salary_text: pay as stated, e.g. "시간당 35,000원".
- benefits: for overseas jobs, support such as airfare, housing, visa, insurance, as a short comma-separated list.
- summary: two or three sentences in your own words for a teacher deciding whether to apply: who is hiring, where, what the role is, key requirements, and the deadline. Do not copy sentences from the posting."""


class LlmUnavailable(Exception):
    """Credentials are missing or rejected, or usage is exhausted: stop sending
    postings this run."""


Extractor = Callable[[dict, str], "dict | None"]


def format_posting(job: dict, text: str) -> str:
    return (
        f"제목: {job.get('title') or ''}\n"
        f"기관: {job.get('institution_name') or '미확인'}\n"
        f"지역: {job.get('location_text') or '미확인'}\n"
        f"마감일: {job.get('deadline') or '미확인'}\n\n"
        f"{text}"
    )


def normalize_llm_fields(data: dict) -> dict:
    """Turn the model's JSON into column values (booleans -> 0/1, is_overseas)."""
    data = dict(data)
    for key in ("newcomer_ok", "demo_lesson"):
        if data.get(key) is not None:
            data[key] = 1 if data[key] else 0
    country = data.get("country")
    data["is_overseas"] = 1 if (country and country != "대한민국") else 0
    return data


def make_extractor(backend: str) -> Extractor | None:
    """The extraction function for a backend, or None when it cannot run here."""
    if backend == "claude-code":
        claude = shutil.which("claude")
        if not claude:
            print("llm fields skipped: the `claude` CLI is not on PATH", file=sys.stderr)
            return None
        return lambda job, text: extract_claude_code(claude, job, text)
    if backend == "api":
        client = make_client()
        return None if client is None else (lambda job, text: extract_llm(client, job, text))
    raise ValueError(f"unknown llm backend: {backend}")


# Phrases in a failed headless run that mean no later posting can succeed either.
CLAUDE_CODE_FATAL = re.compile(
    r"not logged in|please run /login|invalid api key|authentication|usage limit|limit reached|rate limit",
    re.I,
)
CLAUDE_CODE_TIMEOUT = 300


def extract_claude_code(claude: str, job: dict, text: str) -> dict | None:
    """Ask Claude through `claude -p` on the signed-in Claude Code account.

    The posting goes in on stdin (it can exceed the Windows command-line limit),
    tools are off so the model only reads, and --json-schema makes the CLI
    validate the reply into `structured_output`. Runs from the temp directory so
    no project CLAUDE.md or project settings join the prompt.
    """
    command = [
        claude, "-p", "Record the facts of the job posting given on standard input.",
        "--output-format", "json",
        "--json-schema", json.dumps(LLM_SCHEMA),
        "--system-prompt", LLM_SYSTEM,
        "--tools", "",
        "--no-session-persistence",
    ]
    try:
        completed = subprocess.run(
            command,
            input=format_posting(job, text).encode("utf-8"),
            capture_output=True,
            timeout=CLAUDE_CODE_TIMEOUT,
            cwd=tempfile.gettempdir(),
        )
    except subprocess.TimeoutExpired:
        print(f"claude code timed out for job {job.get('job_id')}", file=sys.stderr)
        return None

    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr = completed.stderr.decode("utf-8", errors="replace")
    try:
        reply = json.loads(stdout)
    except json.JSONDecodeError:
        reply = None
    if reply is None or completed.returncode != 0 or reply.get("is_error"):
        message = (reply or {}).get("result") or stderr.strip() or stdout.strip()
        if CLAUDE_CODE_FATAL.search(message):
            raise LlmUnavailable(message[:300])
        print(f"claude code failed for job {job.get('job_id')}: {message[:300]}", file=sys.stderr)
        return None
    if reply.get("stop_reason") == "refusal":
        print(f"llm declined job {job.get('job_id')}", file=sys.stderr)
        return None
    data = reply.get("structured_output")
    if not isinstance(data, dict):
        print(f"claude code returned no structured output for job {job.get('job_id')}", file=sys.stderr)
        return None
    return normalize_llm_fields(data)


def make_client():
    """An Anthropic client, or None when the SDK or a credential is missing."""
    try:
        import anthropic
    except ImportError:
        print("llm fields skipped: install the SDK with `pip install anthropic`", file=sys.stderr)
        return None
    try:
        return anthropic.Anthropic()
    except Exception as exc:  # no API key / profile configured
        print(f"llm fields skipped: {exc}", file=sys.stderr)
        return None


def extract_llm(client, job: dict, text: str) -> dict | None:
    """Ask Claude through the API for the structured fields. Returns None when
    this call fails; raises LlmUnavailable when no later call can succeed either."""
    import anthropic

    posting = format_posting(job, text)
    try:
        # output_config and fallbacks go through extra_body so this also runs
        # on SDK releases older than those parameters.
        response = client.beta.messages.create(
            model=LLM_MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            system=LLM_SYSTEM,
            messages=[{"role": "user", "content": posting}],
            extra_body={
                "fallbacks": "default",
                "output_config": {
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": LLM_SCHEMA},
                },
            },
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        raise LlmUnavailable(str(exc)) from exc
    except TypeError as exc:
        # The SDK raises this before sending when it finds no API key at all.
        raise LlmUnavailable(str(exc)) from exc
    except anthropic.RateLimitError as exc:
        print(f"llm rate limited for job {job.get('job_id')}: {exc}", file=sys.stderr)
        return None
    except anthropic.APIStatusError as exc:
        print(f"llm error {exc.status_code} for job {job.get('job_id')}: {exc.message}", file=sys.stderr)
        return None
    except anthropic.APIConnectionError as exc:
        print(f"llm connection error for job {job.get('job_id')}: {exc}", file=sys.stderr)
        return None

    if response.stop_reason == "refusal":
        print(f"llm declined job {job.get('job_id')}", file=sys.stderr)
        return None
    text_block = next((block.text for block in response.content if block.type == "text"), None)
    if not text_block:
        return None
    return normalize_llm_fields(json.loads(text_block))
