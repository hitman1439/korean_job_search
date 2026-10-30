"""Questions for the institution review (test build only, /test/review.html).

One list feeds both the page (build_site.py embeds it) and the server check in
serve.py, so a question added here is accepted everywhere at once. Every score
is 1-5 and 5 is always the good side. The form asks nothing about the reviewer.
"""

from __future__ import annotations

# (key, area name, short chip label, [(item key, statement)])
AREAS: list[tuple[str, str, str, list[tuple[str, str]]]] = [
    ("pay", "급여·보상", "급여", [
        ("pay_level", "강사료가 다른 기관보다 높은 편이다."),
        ("pay_extra", "시험 출제, 채점, 행사 같은 수업 외 업무에도 보상이 있다."),
        ("pay_ontime", "급여가 약속한 날짜에 정확히 지급된다."),
        ("pay_fair", "일하는 양에 비해 받는 돈이 적정하다."),
    ]),
    ("stability", "고용 안정성", "고용 안정", [
        ("stab_notice", "다음 학기 강의 배정을 미리 알 수 있다."),
        ("stab_hours", "시수가 갑자기 줄어드는 일이 없다."),
        ("stab_legal", "4대 보험, 퇴직금 등 법적 처우를 제대로 해 준다."),
        ("stab_renew", "재계약 기준이 투명하다."),
    ]),
    ("workload", "업무량", "업무량", [
        ("work_admin", "수업 외 행정 업무가 많지 않다."),
        ("work_offhours", "근무시간 외(밤, 주말)에 업무 연락이 거의 없다."),
        ("work_schedule", "시간표와 반 배정이 공정하다."),
    ]),
    ("culture", "조직 분위기", "분위기", [
        ("cult_flat", "위계적이지 않고 수평적이다."),
        ("cult_newcomer", "텃세가 없고 새로 온 교사도 쉽게 적응할 수 있다."),
        ("cult_faction", "라인이나 파벌이 없다."),
        ("cult_voice", "교사가 의견을 자유롭게 말할 수 있다."),
    ]),
    ("leaders", "관리자", "관리자", [
        ("lead_expert", "관리자가 한국어교육 현장을 잘 이해한다."),
        ("lead_protect", "민원이나 문제가 생겼을 때 관리자가 교사를 보호해 준다."),
        ("lead_fair", "관리자가 모든 교사를 공정하게 대한다."),
    ]),
    ("peers", "동료 관계", "동료", [
        ("peer_share", "동료들과 수업 자료를 서로 공유한다."),
        ("peer_gossip", "동료 간 견제나 뒷담화가 없다."),
        ("peer_talk", "어려운 일을 동료와 편하게 상의할 수 있다."),
    ]),
    ("teaching", "수업·교육과정", "수업", [
        ("teach_material", "커리큘럼과 교재가 잘 갖춰져 있다."),
        ("teach_freedom", "수업 방식에 교사 재량이 보장된다."),
        ("teach_class", "반 인원과 레벨 편성이 적절하다."),
        ("teach_grading", "승급과 평가 기준이 제대로 지켜진다."),
    ]),
    ("growth", "성장·경력", "배울 점", [
        ("grow_learn", "교사로서 배울 점이 많다."),
        ("grow_support", "연수, 학회 참가 등 전문성 개발을 지원한다."),
        ("grow_chance", "교재 개발, 연구 등 다양한 업무를 경험할 기회가 있다."),
        ("grow_career", "이곳 경력이 이직할 때 도움이 된다."),
    ]),
    ("students", "학생", "학생", [
        ("stud_motive", "학생들의 학습 의욕이 높다."),
        ("stud_attend", "학생들의 출석률과 수업 태도가 좋다."),
        ("stud_respect", "학생들이 교사를 존중한다."),
        ("stud_mix", "학생 국적 구성이 다양하다."),
    ]),
    ("admin", "행정 지원", "행정", [
        ("adm_help", "행정실이 교사에게 협조적이고 빠르게 처리해 준다."),
        ("adm_notice", "학기 일정과 공지가 미리, 명확하게 전달된다."),
        ("adm_burden", "학생 관리(출결 추적, 비자 등) 부담이 교사에게 넘어오지 않는다."),
    ]),
    ("facilities", "시설·근무 환경", "시설", [
        ("fac_room", "강의실 시설과 기자재가 잘 갖춰져 있다."),
        ("fac_desk", "개인 책상, PC 등 교사 업무 공간이 충분하다."),
        ("fac_amenity", "휴게 공간, 도서관 등 편의시설을 이용할 수 있다."),
    ]),
    ("location", "위치·교통", "교통", [
        ("loc_transit", "대중교통으로 다니기 편하다."),
        ("loc_commute", "주차나 셔틀버스 등 출퇴근 지원이 있다."),
    ]),
]

# Asked last, after the reviewer has walked through the areas.
CLOSING: list[tuple[str, str]] = [
    ("stay", "이곳에서 계속 일하고 싶다."),
    ("recommend", "지인에게 이곳을 추천하고 싶다."),
    ("expect", "들어오기 전 기대보다 만족스럽다."),
]

# Facts about the job, picked from ranges; all optional.
FACTS: list[tuple[str, str, list[str]]] = [
    ("hourly_pay", "시간당 강사료", ["3만원 미만", "3만~4만원", "4만~5만원", "5만원 이상"]),
    ("weekly_hours", "주당 강의 시수", ["10시간 미만", "10~14시간", "15~19시간", "20시간 이상"]),
    ("class_size", "한 반 학생 수", ["10명 이하", "11~15명", "16~20명", "21명 이상"]),
    ("insurance", "4대 보험", ["가입", "미가입"]),
    ("contract", "계약 기간", ["한 학기", "1년", "2년 이상"]),
]

OVERALL_LABELS = ["매우 나빴어요", "나빴어요", "보통이에요", "좋았어요", "매우 좋았어요"]
AREA_LABELS = ["매우 나쁨", "나쁨", "보통", "좋음", "매우 좋음"]
AGREE_LABELS = ["전혀 아니다", "아니다", "보통", "그렇다", "매우 그렇다"]

MAX_ORG = 80
MAX_COMMENT = 1000

AREA_KEYS = {key for key, *_ in AREAS}
ITEM_KEYS = {item for *_, items in AREAS for item, _ in items}
CLOSING_KEYS = {key for key, _ in CLOSING}
FACT_OPTIONS = {key: options for key, _, options in FACTS}


def page_data() -> dict:
    """What review.js needs to draw the form."""
    return {
        "areas": [
            {"key": key, "name": name, "chip": chip, "items": [{"key": k, "text": t} for k, t in items]}
            for key, name, chip, items in AREAS
        ],
        "closing": [{"key": k, "text": t} for k, t in CLOSING],
        "facts": [{"key": k, "label": label, "options": options} for k, label, options in FACTS],
        "labels": {"overall": OVERALL_LABELS, "area": AREA_LABELS, "agree": AGREE_LABELS},
    }


def _scores(value: object, allowed: set[str]) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    out = {}
    for key, score in value.items():
        # bool is an int in Python; true must not pass as 1.
        if key not in allowed or isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
            return None
        out[key] = score
    return out


def clean_review(data: object) -> dict | None:
    """The review as it will be stored, or None if anything is off."""
    if not isinstance(data, dict):
        return None
    org = data.get("org")
    overall = data.get("overall")
    if not isinstance(org, str) or not 0 < len(org.strip()) <= MAX_ORG:
        return None
    if isinstance(overall, bool) or not isinstance(overall, int) or not 1 <= overall <= 5:
        return None
    lists = {}
    for name in ("good", "bad"):
        value = data.get(name, [])
        if not isinstance(value, list) or not all(isinstance(k, str) and k in AREA_KEYS for k in value):
            return None
        lists[name] = sorted(set(value))
    areas = _scores(data.get("areas", {}), AREA_KEYS)
    items = _scores(data.get("items", {}), ITEM_KEYS)
    closing = _scores(data.get("closing", {}), CLOSING_KEYS)
    if areas is None or items is None or closing is None:
        return None
    facts = data.get("facts", {})
    if not isinstance(facts, dict) or any(FACT_OPTIONS.get(k) is None or v not in FACT_OPTIONS[k] for k, v in facts.items()):
        return None
    comment = data.get("comment", "")
    if not isinstance(comment, str) or len(comment) > MAX_COMMENT:
        return None
    return {
        "org": org.strip(), "overall": overall, **lists, "areas": areas, "items": items,
        "closing": closing, "facts": facts, "comment": comment.strip(),
    }
