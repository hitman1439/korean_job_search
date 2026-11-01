"""Questions for 근무 후기 (test build only, under /test).

One list feeds both the pages (build_site.py embeds it) and the server check in
serve.py, so a question added here is accepted everywhere at once. Every score
is 1-5 and 5 is always the good side. Nothing is required and nothing is asked
about the reviewer: a review is whatever statements they chose to answer.

Wording rule (legal): every statement and answer is the reviewer's own
perception ("~라고 느꼈다", "만족했다"), never a fact about the institution. No
question may imply a legal violation (임금 체불, 4대 보험, 퇴직금, 시수 쪼개기),
single out one person (원장, 주임), or speak about students' purposes, visas or
nationalities. The results page then reads as "응답자 체감 평균", and the site
itself states nothing about any institution.
"""

from __future__ import annotations

import hashlib

# Five areas, three statements each. (key, area name, [(statement key, statement)])
AREAS: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("pay", "급여·처우", [
        ("pay_level", "강사료 수준에 대체로 만족했다."),
        ("pay_extra", "수업 외 업무에 대한 보상이 적절하다고 느꼈다."),
        ("pay_care", "급여와 처우 전반에 대체로 만족했다."),
    ]),
    ("stability", "고용 안정성", [
        ("stab_notice", "다음 학기 강의 배정을 미리 알 수 있어 계획을 세우기 좋았다."),
        ("stab_hours", "강의 시수가 안정적이라고 느꼈다."),
        ("stab_renew", "재계약 과정이 납득할 만하다고 느꼈다."),
    ]),
    ("workload", "업무 강도", [
        ("work_admin", "수업 외 업무량이 적당하다고 느꼈다."),
        ("work_offhours", "근무시간 외 연락이 부담스럽지 않았다."),
        ("work_support", "행정 지원 덕분에 수업에 집중할 수 있었다."),
    ]),
    ("people", "사람과 분위기", [
        ("cult_newcomer", "새로 온 교사도 적응하기 편한 분위기였다."),
        ("cult_flat", "구성원 사이의 소통이 편하다고 느꼈다."),
        ("org_support", "어려운 일이 생겼을 때 기관에서 도움을 받을 수 있다고 느꼈다."),
    ]),
    ("teaching", "수업과 성장", [
        ("class_joy", "수업하는 일이 보람 있었다."),
        ("teach_freedom", "수업 방식에 교사 재량이 충분하다고 느꼈다."),
        ("grow_learn", "교사로서 배우고 성장할 기회가 있었다."),
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
# asks its area's statements as feelings; an item's five answers are listed
# from score 1 to 5, and the page shows that number in front of each. "more" is
# offered at the end of a scene and can be passed. Every statement and fact
# appears once. A question is ("item", key, prompt, [answer for 1, …, for 5])
# or ("fact", key, prompt).
STORY: list[dict] = [
    {"key": "office", "title": "교무실 문을 열면", "scene": "아침, {org} 교무실 문을 열어요. 먼저 와 있던 선생님들이 보여요.", "core": [
        ("item", "cult_newcomer", "처음 이곳에 왔을 때, 적응은 어땠나요?", [
            "적응하기 많이 힘들었어요", "조금 외롭게 느껴졌어요", "그럭저럭 적응했어요",
            "대체로 편하게 적응했어요", "따뜻하게 맞아 줘서 금방 적응했어요"]),
        ("item", "cult_flat", "선생님들 사이의 소통은 어떻게 느껴졌나요?", [
            "많이 어렵게 느껴졌어요", "조금 조심스러웠어요", "보통이었어요",
            "대체로 편했어요", "아주 편하고 자유로웠어요"]),
        ("item", "org_support", "곤란한 일이 생겼을 때, 기관의 도움은 어떻게 느껴졌나요?", [
            "도움을 받기 어렵다고 느꼈어요", "조금 아쉬웠어요", "보통이었어요",
            "대체로 도움이 됐어요", "든든하게 느껴졌어요"]),
    ], "more": []},
    {"key": "class", "title": "수업 종이 울리면", "scene": "종이 울리고, 학생들이 하나둘 들어와요.", "core": [
        ("item", "class_joy", "학생들과 함께한 수업 시간, 어떠셨어요?", [
            "많이 지쳤어요", "보람보다 힘든 게 컸어요", "보통이었어요",
            "대체로 보람 있었어요", "정말 즐겁고 보람 있었어요"]),
        ("item", "teach_freedom", "수업을 내 방식대로 꾸릴 수 있었나요?", [
            "거의 그럴 수 없었어요", "조금 답답했어요", "보통이었어요",
            "대체로 자유로웠어요", "아주 자유로웠어요"]),
        ("item", "grow_learn", "이곳에서 가르치며, 교사로서 나는…", [
            "성장하기 어렵다고 느꼈어요", "조금 아쉬웠어요", "보통이었어요",
            "꽤 배웠어요", "많이 성장했어요"]),
    ], "more": [
        ("fact", "class_size", "한 반 학생은 보통 몇 명이었나요?"),
    ]},
    {"key": "after", "title": "수업이 끝나도", "scene": "수업은 끝났지만, 할 일이 남아 있어요.", "core": [
        ("item", "work_admin", "수업 말고 해야 하는 일의 양은 어떻게 느껴졌나요?", [
            "매우 많다고 느꼈어요", "조금 많다고 느꼈어요", "적당했어요",
            "부담이 적었어요", "거의 없어서 수업에 집중했어요"]),
        ("item", "work_offhours", "퇴근 후나 주말의 업무 연락은 어떻게 느껴졌나요?", [
            "많이 부담스러웠어요", "가끔 부담스러웠어요", "보통이었어요",
            "거의 신경 쓰이지 않았어요", "전혀 부담이 없었어요"]),
        ("item", "work_support", "행정 지원은 어떻게 느껴졌나요?", [
            "많이 아쉬웠어요", "조금 아쉬웠어요", "보통이었어요",
            "대체로 든든했어요", "아주 든든했어요"]),
    ], "more": [
        ("fact", "weekly_hours", "일주일에 강의는 몇 시간 정도였나요?"),
    ]},
    {"key": "payday", "title": "월급날", "scene": "오늘은 월급날이에요. 통장을 확인해 봐요.", "core": [
        ("item", "pay_level", "강사료 수준, 내 기준에서 만족스러웠나요?", [
            "많이 아쉬웠어요", "조금 아쉬웠어요", "보통이었어요", "대체로 만족했어요", "아주 만족했어요"]),
        ("item", "pay_extra", "수업 외 업무에 대한 보상은 어떻게 느껴졌나요?", [
            "많이 아쉬웠어요", "조금 아쉬웠어요", "보통이었어요", "대체로 적절했어요", "충분했어요"]),
        ("item", "pay_care", "급여와 처우 전반, 어떻게 느껴졌나요?", [
            "많이 아쉬웠어요", "조금 아쉬웠어요", "보통이었어요", "대체로 만족했어요", "아주 만족했어요"]),
    ], "more": [
        ("fact", "hourly_pay", "시간당 강사료는 어느 정도였나요?"),
    ]},
    {"key": "semester", "title": "학기가 끝나 갈 무렵", "scene": "학기가 끝나 가요. 다음 학기 이야기가 나와요.", "core": [
        ("item", "stab_hours", "다음 학기 시수, 안정적이라고 느꼈나요?", [
            "늘 불안했어요", "조금 불안했어요", "보통이었어요", "대체로 안정적이었어요", "아주 안정적이었어요"]),
        ("item", "stab_notice", "다음 학기 강의 배정, 미리 알 수 있었나요?", [
            "너무 늦게 알게 돼 힘들었어요", "조금 늦다고 느꼈어요", "보통이었어요",
            "대체로 미리 알았어요", "충분히 미리 알아서 계획하기 좋았어요"]),
        ("item", "stab_renew", "재계약 과정은 납득할 만했나요?", [
            "납득하기 어려웠어요", "조금 아쉬웠어요", "보통이었어요", "대체로 납득됐어요", "충분히 납득됐어요"]),
    ], "more": []},
]

# The ending card, shown only to the reviewer: the best and worst remembered area.
AREA_TYPES: dict[str, tuple[str, str]] = {
    "pay": ("급여에 만족했던 곳", "급여가 아쉬웠던 곳"),
    "stability": ("다음 학기가 든든했던 곳", "다음 학기가 불안했던 곳"),
    "workload": ("수업에 집중할 수 있었던 곳", "수업 외 일이 많게 느껴진 곳"),
    "people": ("사람 덕분에 편했던 곳", "소통이 어려웠던 곳"),
    "teaching": ("가르치는 보람이 컸던 곳", "수업이 답답했던 곳"),
}

MAX_ORG = 80
MAX_COMMENT = 1000
# Results stay hidden until this many reviews: with fewer, a reviewer in a
# small staff room is easy to guess.
PUBLIC_MIN = 5

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
        "publicMin": PUBLIC_MIN,
    }


def clean_review(data: object) -> dict | None:
    """The review as it will be stored, or None if anything is off, nothing was
    answered, or the reviewer did not take the pledge (직접 경험, 본인 책임)."""
    if not isinstance(data, dict) or data.get("pledge") is not True:
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
    """Totals for one institution's results page.

    `reviews` are the shown ones, with "comment" set only once the operator
    approved it. Comments carry no date and come in a fixed but meaningless
    order, so their position says nothing about when or by whom.
    """
    items: dict[str, list[int]] = {}
    facts: dict[str, dict[str, int]] = {}
    comments = []
    for review in reviews:
        for key, score in review["items"].items():
            if key not in ITEM_KEYS:
                continue  # a statement since retired
            total = items.setdefault(key, [0, 0])
            total[0] += score
            total[1] += 1
        for key, value in review["facts"].items():
            if key in FACT_OPTIONS:
                facts.setdefault(key, {})[value] = facts.get(key, {}).get(value, 0) + 1
        if review.get("comment"):
            comments.append(review["comment"])
    comments.sort(key=lambda text: hashlib.sha256(text.encode("utf-8")).hexdigest())
    return {
        "count": len(reviews), "public": len(reviews) >= PUBLIC_MIN, "min": PUBLIC_MIN,
        "items": items, "facts": facts, "comments": comments,
    }
