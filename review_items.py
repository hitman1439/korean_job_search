"""Questions for the institution review (test build only, under /test).

One list feeds both the pages (build_site.py embeds it) and the server check in
serve.py, so a question added here is accepted everywhere at once. Every score
is 1-5 and 5 is always the good side. Nothing is required and nothing is asked
about the reviewer: a review is whatever statements they chose to answer.
"""

from __future__ import annotations

# Five areas that matter most, three statements each.
# (key, area name, [(statement key, statement)])
AREAS: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("pay", "급여·처우", [
        ("pay_level", "강사료가 다른 기관보다 높은 편이다."),
        ("pay_extra", "시험 출제, 채점, 행사 같은 수업 외 업무에도 보상이 있다."),
        ("pay_legal", "급여 지급과 4대 보험, 퇴직금 등 법적 처우가 정확하다."),
    ]),
    ("stability", "고용 안정성", [
        ("stab_notice", "다음 학기 강의 배정을 미리 알 수 있다."),
        ("stab_hours", "시수가 갑자기 줄어드는 일이 없다."),
        ("stab_renew", "재계약 기준이 투명하다."),
    ]),
    ("workload", "업무 강도", [
        ("work_admin", "수업 외 행정 업무가 많지 않다."),
        ("work_offhours", "근무시간 외(밤, 주말)에 업무 연락이 거의 없다."),
        ("adm_burden", "학생 관리(출결 추적, 비자 등) 부담이 교사에게 넘어오지 않는다."),
    ]),
    ("people", "사람과 분위기", [
        ("cult_newcomer", "텃세가 없고 새로 온 교사도 쉽게 적응할 수 있다."),
        ("cult_flat", "위계적이지 않고 수평적이다."),
        ("lead_protect", "민원이나 문제가 생겼을 때 관리자가 교사를 보호해 준다."),
    ]),
    ("teaching", "수업과 성장", [
        ("stud_motive", "학생들의 학습 의욕과 수업 태도가 좋다."),
        ("teach_freedom", "수업 방식에 교사 재량이 보장된다."),
        ("grow_learn", "교사로서 배울 점이 많다."),
    ]),
]

# Facts about the job, picked from ranges instead of scored.
FACTS: list[tuple[str, str, list[str]]] = [
    ("hourly_pay", "시간당 강사료", ["3만원 미만", "3만~4만원", "4만~5만원", "5만원 이상"]),
    ("weekly_hours", "주당 강의 시수", ["10시간 미만", "10~14시간", "15~19시간", "20시간 이상"]),
    ("class_size", "한 반 학생 수", ["10명 이하", "11~15명", "16~20명", "21명 이상"]),
]

AGREE_LABELS = ["전혀 아니다", "아니다", "보통", "그렇다", "매우 그렇다"]

# The story form, told as one working day like a personality quiz. Each scene
# asks its area's statements as situations; an item's five answers are listed
# from score 1 to 5, and the page shows that number in front of each. "more" is
# offered at the end of a scene and can be passed. Every statement and fact
# appears once. A question is ("item", key, prompt, [answer for 1, …, for 5])
# or ("fact", key, prompt).
STORY: list[dict] = [
    {"key": "office", "title": "교무실 문을 열면", "scene": "아침, {org} 교무실 문을 열어요. 먼저 와 있던 선생님들이 보여요.", "core": [
        ("item", "cult_newcomer", "처음 이곳에 온 날을 떠올려 보세요. 기존 선생님들은요?", [
            "보이지 않는 벽이 느껴졌어요", "알아서 하라는 분위기였어요", "필요한 것만 알려 줬어요",
            "물어보면 친절하게 답해 줬어요", "먼저 다가와 이것저것 알려 줬어요"]),
        ("item", "cult_flat", "선배와 후배, 전임과 강사 사이는요?", [
            "군대 같았어요", "말 한마디도 눈치를 봤어요", "예의를 차리는 만큼 거리가 있었어요",
            "어렵지 않게 지냈어요", "직급보다 사람으로 대했어요"]),
        ("item", "lead_protect", "학생이 성적 때문에 민원을 넣은 날, 관리자는요?", [
            "모든 책임을 나에게 돌렸어요", "학생 쪽 말만 들었어요", "알아서 해결하라고 했어요",
            "중간에서 잘 조율해 줬어요", "사실을 확인하고 내 편에 서 줬어요"]),
    ], "more": []},
    {"key": "class", "title": "수업 종이 울리면", "scene": "종이 울리고, 학생들이 하나둘 들어와요.", "core": [
        ("item", "stud_motive", "학생들의 눈빛은 어땠나요?", [
            "공부보다 다른 목적이 커 보였어요", "출석 때문에 앉아 있는 학생이 많았어요", "반반이었어요",
            "대체로 열심이었어요", "배우고 싶어 반짝였어요"]),
        ("item", "teach_freedom", "오늘 수업, 내 방식대로 해 볼 수 있었나요?", [
            "PPT 글자 하나까지 맞춰야 했어요", "정해진 대로만 해야 했어요", "작은 활동 정도는 넣을 수 있었어요",
            "진도만 맞추면 괜찮았어요", "교재 밖 활동도 자유롭게 했어요"]),
        ("item", "grow_learn", "이곳에서 가르치며 나는…", [
            "소모되기만 했어요", "버티는 법만 늘었어요", "그럭저럭 경력이 쌓였어요",
            "배운 게 꽤 있어요", "교사로서 확실히 성장했어요"]),
    ], "more": [
        ("fact", "class_size", "한 반 학생은 보통 몇 명이었나요?"),
    ]},
    {"key": "after", "title": "수업이 끝나도", "scene": "수업은 끝났지만, 할 일이 남아 있어요.", "core": [
        ("item", "work_admin", "수업 말고 해야 하는 일은요?", [
            "행정 직원인지 교사인지 헷갈렸어요", "보고서와 서류가 수업만큼 많았어요", "가끔 몰리는 시기가 있었어요",
            "출결·성적 정리 정도였어요", "거의 없어서 수업에만 집중했어요"]),
        ("item", "work_offhours", "밤 10시, 휴대폰이 울려요.", [
            "주말에도 답장을 해야 했어요", "단톡방 업무 지시가 일상이었어요", "시험 기간에는 종종 그랬어요",
            "가끔 급한 공지 정도였어요", "그럴 일이 없었어요"]),
        ("item", "adm_burden", "결석한 학생, 비자 서류… 누가 챙겼나요?", [
            "이탈 학생 책임까지 교사에게 왔어요", "출결 추적은 교사 몫이었어요", "행정실과 반반 나눠 했어요",
            "가끔 연락 정도만 했어요", "행정실이 다 맡았어요"]),
    ], "more": [
        ("fact", "weekly_hours", "일주일에 강의는 몇 시간 정도였나요?"),
    ]},
    {"key": "payday", "title": "월급날", "scene": "오늘은 월급날이에요. 통장을 확인해 봐요.", "core": [
        ("item", "pay_level", "찍힌 금액, 다른 기관과 비교하면요?", [
            "업계 최저 수준이에요", "조금 낮은 편이에요", "비슷한 편이에요", "조금 높은 편이에요", "확실히 높은 편이에요"]),
        ("item", "pay_extra", "시험 출제, 채점, 행사 인솔… 수당은요?", [
            "당연히 할 일 취급이었어요", "대부분 무급이었어요", "일부는 줬어요", "대부분 챙겨 줬어요", "하나하나 다 챙겨 줬어요"]),
        ("item", "pay_legal", "월급 날짜, 4대 보험, 퇴직금은요?", [
            "자주 밀리고 보험도 없었어요", "시수를 쪼개 피하는 느낌이었어요", "가끔 늦거나 빠진 게 있었어요",
            "대체로 잘 챙겨 줬어요", "법대로, 하루도 틀림없었어요"]),
    ], "more": [
        ("fact", "hourly_pay", "시간당 강사료는 어느 정도였나요?"),
    ]},
    {"key": "semester", "title": "학기가 끝나 갈 무렵", "scene": "학기가 끝나 가요. 다음 학기 이야기가 나와요.", "core": [
        ("item", "stab_hours", "다음 학기 시수는요?", [
            "개강 직전까지 0시간일 수도 있었어요", "갑자기 줄어든 적이 있어요", "학기마다 들쭉날쭉했어요",
            "조금씩 바뀌어도 예상할 수 있었어요", "늘 비슷하게 보장됐어요"]),
        ("item", "stab_notice", "다음 학기 강의 배정은 언제 알았나요?", [
            "개강하고 나서야요", "개강 1주 전에요", "2주쯤 전에요", "3~4주 전에요", "한 달도 더 전에요"]),
        ("item", "stab_renew", "재계약, 기준을 알 수 있었나요?", [
            "윗사람 마음이었어요", "누구는 되고 누구는 안 되는 이유를 몰랐어요", "대충은 알았어요",
            "기준이 있고 대체로 지켜졌어요", "기준이 공개되고 납득됐어요"]),
    ], "more": []},
]

# The ending card, like a quiz result: the best and worst remembered area.
AREA_TYPES: dict[str, tuple[str, str]] = {
    "pay": ("월급날이 기다려지는 곳", "월급날엔 한숨이 나오는 곳"),
    "stability": ("다음 학기 걱정이 없는 곳", "다음 학기가 늘 불안한 곳"),
    "workload": ("수업에만 집중할 수 있는 곳", "수업 말고도 할 일이 많은 곳"),
    "people": ("사람 덕분에 다니는 곳", "사람 때문에 힘든 곳"),
    "teaching": ("가르치는 맛이 나는 곳", "수업이 답답한 곳"),
}

MAX_ORG = 80
MAX_COMMENT = 1000

ITEM_KEYS = {item for _, _, items in AREAS for item, _ in items}
FACT_OPTIONS = {key: options for key, _, options in FACTS}


def _question(q: tuple) -> dict:
    if q[0] == "fact":
        return {"fact": q[1], "q": q[2], "options": [{"text": o} for o in FACT_OPTIONS[q[1]]]}
    return {"item": q[1], "q": q[2], "options": [{"text": t, "score": n} for n, t in enumerate(q[3], 1)]}


def page_data() -> dict:
    """What the review pages need: statements for results, the story for the form."""
    return {
        "areas": [
            {"key": key, "name": name, "items": [{"key": k, "text": t} for k, t in items]}
            for key, name, items in AREAS
        ],
        "facts": [{"key": k, "label": label, "options": options} for k, label, options in FACTS],
        "labels": AGREE_LABELS,
        "story": [
            {"key": c["key"], "title": c["title"], "scene": c["scene"],
             "core": [_question(q) for q in c["core"]], "more": [_question(q) for q in c["more"]]}
            for c in STORY
        ],
        "types": {key: list(pair) for key, pair in AREA_TYPES.items()},
    }


def clean_review(data: object) -> dict | None:
    """The review as it will be stored, or None if anything is off or nothing was answered."""
    if not isinstance(data, dict):
        return None
    org = data.get("org")
    if not isinstance(org, str) or not 0 < len(org.strip()) <= MAX_ORG:
        return None
    items = data.get("items", {})
    if not isinstance(items, dict):
        return None
    for key, score in items.items():
        # bool is an int in Python; true must not pass as 1.
        if key not in ITEM_KEYS or isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
            return None
    facts = data.get("facts", {})
    if not isinstance(facts, dict) or any(FACT_OPTIONS.get(k) is None or v not in FACT_OPTIONS[k] for k, v in facts.items()):
        return None
    comment = data.get("comment", "")
    if not isinstance(comment, str) or len(comment) > MAX_COMMENT:
        return None
    comment = comment.strip()
    if not (items or facts or comment):
        return None
    return {"org": " ".join(org.split()), "items": items, "facts": facts, "comment": comment}


def summarize(reviews: list[dict]) -> dict:
    """Totals for one institution's results page: per-statement sums, fact tallies, comments."""
    items: dict[str, list[int]] = {}
    facts: dict[str, dict[str, int]] = {}
    comments = []
    for review in reviews:
        for key, score in review["items"].items():
            total = items.setdefault(key, [0, 0])
            total[0] += score
            total[1] += 1
        for key, value in review["facts"].items():
            facts.setdefault(key, {})[value] = facts.get(key, {}).get(value, 0) + 1
        if review["comment"]:
            comments.append({"text": review["comment"], "on": review["on"]})
    comments.sort(key=lambda c: c["on"], reverse=True)
    return {"count": len(reviews), "items": items, "facts": facts, "comments": comments}
