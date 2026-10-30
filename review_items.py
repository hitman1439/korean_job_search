"""Questions for the institution review (test build only, under /test).

One list feeds both the pages (build_site.py embeds it) and the server check in
serve.py, so a question added here is accepted everywhere at once. Every score
is 1-5 and 5 is always the good side. Nothing is required and nothing is asked
about the reviewer: a review is whatever statements they chose to answer.
"""

from __future__ import annotations

# (key, area name, [(statement key, statement)])
AREAS: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("overall", "종합", [
        ("overall_sat", "전반적으로 만족스럽다."),
        ("stay", "이곳에서 계속 일하고 싶다."),
        ("recommend", "지인에게 이곳을 추천하고 싶다."),
        ("expect", "들어오기 전 기대보다 만족스럽다."),
    ]),
    ("pay", "급여·보상", [
        ("pay_level", "강사료가 다른 기관보다 높은 편이다."),
        ("pay_extra", "시험 출제, 채점, 행사 같은 수업 외 업무에도 보상이 있다."),
        ("pay_ontime", "급여가 약속한 날짜에 정확히 지급된다."),
        ("pay_fair", "일하는 양에 비해 받는 돈이 적정하다."),
    ]),
    ("stability", "고용 안정성", [
        ("stab_notice", "다음 학기 강의 배정을 미리 알 수 있다."),
        ("stab_hours", "시수가 갑자기 줄어드는 일이 없다."),
        ("stab_legal", "4대 보험, 퇴직금 등 법적 처우를 제대로 해 준다."),
        ("stab_renew", "재계약 기준이 투명하다."),
    ]),
    ("workload", "업무량", [
        ("work_admin", "수업 외 행정 업무가 많지 않다."),
        ("work_offhours", "근무시간 외(밤, 주말)에 업무 연락이 거의 없다."),
        ("work_schedule", "시간표와 반 배정이 공정하다."),
    ]),
    ("culture", "조직 분위기", [
        ("cult_flat", "위계적이지 않고 수평적이다."),
        ("cult_newcomer", "텃세가 없고 새로 온 교사도 쉽게 적응할 수 있다."),
        ("cult_faction", "라인이나 파벌이 없다."),
        ("cult_voice", "교사가 의견을 자유롭게 말할 수 있다."),
    ]),
    ("leaders", "관리자", [
        ("lead_expert", "관리자가 한국어교육 현장을 잘 이해한다."),
        ("lead_protect", "민원이나 문제가 생겼을 때 관리자가 교사를 보호해 준다."),
        ("lead_fair", "관리자가 모든 교사를 공정하게 대한다."),
    ]),
    ("peers", "동료 관계", [
        ("peer_share", "동료들과 수업 자료를 서로 공유한다."),
        ("peer_gossip", "동료 간 견제나 뒷담화가 없다."),
        ("peer_talk", "어려운 일을 동료와 편하게 상의할 수 있다."),
    ]),
    ("teaching", "수업·교육과정", [
        ("teach_material", "커리큘럼과 교재가 잘 갖춰져 있다."),
        ("teach_freedom", "수업 방식에 교사 재량이 보장된다."),
        ("teach_class", "반 인원과 레벨 편성이 적절하다."),
        ("teach_grading", "승급과 평가 기준이 제대로 지켜진다."),
    ]),
    ("growth", "성장·경력", [
        ("grow_learn", "교사로서 배울 점이 많다."),
        ("grow_support", "연수, 학회 참가 등 전문성 개발을 지원한다."),
        ("grow_chance", "교재 개발, 연구 등 다양한 업무를 경험할 기회가 있다."),
        ("grow_career", "이곳 경력이 이직할 때 도움이 된다."),
    ]),
    ("students", "학생", [
        ("stud_motive", "학생들의 학습 의욕이 높다."),
        ("stud_attend", "학생들의 출석률과 수업 태도가 좋다."),
        ("stud_respect", "학생들이 교사를 존중한다."),
        ("stud_mix", "학생 국적 구성이 다양하다."),
    ]),
    ("admin", "행정 지원", [
        ("adm_help", "행정실이 교사에게 협조적이고 빠르게 처리해 준다."),
        ("adm_notice", "학기 일정과 공지가 미리, 명확하게 전달된다."),
        ("adm_burden", "학생 관리(출결 추적, 비자 등) 부담이 교사에게 넘어오지 않는다."),
    ]),
    ("facilities", "시설·근무 환경", [
        ("fac_room", "강의실 시설과 기자재가 잘 갖춰져 있다."),
        ("fac_desk", "개인 책상, PC 등 교사 업무 공간이 충분하다."),
        ("fac_amenity", "휴게 공간, 도서관 등 편의시설을 이용할 수 있다."),
    ]),
    ("location", "위치·교통", [
        ("loc_transit", "대중교통으로 다니기 편하다."),
        ("loc_commute", "주차나 셔틀버스 등 출퇴근 지원이 있다."),
    ]),
]

# Facts about the job, picked from ranges instead of scored.
FACTS: list[tuple[str, str, list[str]]] = [
    ("hourly_pay", "시간당 강사료", ["3만원 미만", "3만~4만원", "4만~5만원", "5만원 이상"]),
    ("weekly_hours", "주당 강의 시수", ["10시간 미만", "10~14시간", "15~19시간", "20시간 이상"]),
    ("class_size", "한 반 학생 수", ["10명 이하", "11~15명", "16~20명", "21명 이상"]),
    ("insurance", "4대 보험", ["가입", "미가입"]),
    ("contract", "계약 기간", ["한 학기", "1년", "2년 이상"]),
]

AGREE_LABELS = ["전혀 아니다", "아니다", "보통", "그렇다", "매우 그렇다"]

# The form is told as one working day, like a personality quiz: each scene asks
# a statement above as a situation, and each answer carries the 1-5 score that
# statement gets. "core" questions are the short path; "more" are offered at
# the end of a scene and can be passed. Every statement and fact appears once.
# A question is ("item", key, prompt, [(answer, score)]) or ("fact", key, prompt).
STORY: list[dict] = [
    {"key": "commute", "title": "출근길", "scene": "아침 8시 반, {org}(으)로 출근하는 길이에요.", "core": [
        ("item", "loc_transit", "집을 나서 강의실까지, 그 길은 어땠나요?", [
            ("역에서 내리면 금방, 발걸음이 가벼웠어요", 5), ("조금 걷지만 괜찮았어요", 4),
            ("버스를 갈아타고 언덕까지… 매일이 운동이었어요", 2), ("출근만으로 하루 힘의 반을 썼어요", 1)]),
    ], "more": [
        ("item", "loc_commute", "차로 오거나 셔틀을 타야 한다면요?", [
            ("교직원 주차도 셔틀도 넉넉했어요", 5), ("있긴 한데 시간이 잘 안 맞았어요", 3),
            ("따로 지원이 없어 알아서 다녔어요", 2), ("주차는 꿈도 못 꿨어요", 1)]),
    ]},
    {"key": "building", "title": "강의실에 들어서며", "scene": "건물에 들어서 오늘 수업할 강의실 문을 열어요.", "core": [
        ("item", "fac_room", "프로젝터와 컴퓨터를 켜 봐요. 어떤가요?", [
            ("켜자마자 바로, 늘 잘 됐어요", 5), ("가끔 말썽이지만 쓸 만했어요", 4),
            ("고장 난 걸 달래 가며 썼어요", 2), ("칠판과 분필이 제일 믿음직했어요", 1)]),
    ], "more": [
        ("item", "fac_desk", "수업 준비를 할 내 자리는요?", [
            ("내 책상과 컴퓨터가 있었어요", 5), ("공용 자리지만 앉을 곳은 있었어요", 3),
            ("빈자리를 찾아 떠돌았어요", 2), ("앉을 곳이 없어 복도나 카페로 갔어요", 1)]),
        ("item", "fac_amenity", "쉬는 시간, 잠깐 숨 돌릴 곳은요?", [
            ("휴게실도 도서관도 편하게 썼어요", 5), ("작지만 쉴 곳은 있었어요", 4),
            ("쉴 곳이 마땅치 않았어요", 2), ("교사는 못 쓰는 곳이 많았어요", 1)]),
    ]},
    {"key": "office", "title": "교무실 문을 열면", "scene": "교무실 문을 열어요. 먼저 와 있던 선생님들이 보여요.", "core": [
        ("item", "cult_newcomer", "처음 이곳에 온 날을 떠올려 보세요. 기존 선생님들은요?", [
            ("먼저 다가와 이것저것 알려 줬어요", 5), ("물어보면 친절하게 답해 줬어요", 4),
            ("알아서 하라는 분위기였어요", 2), ("보이지 않는 벽이 느껴졌어요", 1)]),
        ("item", "peer_talk", "수업이 잘 안 풀린 날, 옆자리 동료에게…", [
            ("바로 털어놓고 같이 고민했어요", 5), ("친한 몇 명에게만 얘기했어요", 4),
            ("약점 잡힐까 봐 혼자 삭였어요", 2), ("얘기할 사람이 없었어요", 1)]),
    ], "more": [
        ("item", "cult_flat", "선배와 후배, 전임과 강사 사이는요?", [
            ("직급보다 사람으로 대했어요", 5), ("예의는 있지만 어렵지 않았어요", 4),
            ("말 한마디도 눈치를 봤어요", 2), ("군대 같았어요", 1)]),
        ("item", "cult_voice", "회의에서 다른 의견이 있을 때는요?", [
            ("편하게 말했고, 실제로 바뀐 적도 있어요", 5), ("말할 수는 있었어요", 4),
            ("말해 봤자 달라지는 게 없었어요", 2), ("말하면 찍혔어요", 1)]),
        ("item", "cult_faction", "점심시간, 삼삼오오 모이는 무리가 있었나요?", [
            ("그때그때 섞여서 먹었어요", 5), ("친한 사람끼리 먹지만 편 가르기는 없었어요", 4),
            ("라인이 있다는 걸 다들 알았어요", 2), ("어느 편인지가 반 배정까지 좌우했어요", 1)]),
        ("item", "peer_share", "좋은 활동지를 만들었을 때, 이곳에서는…", [
            ("공유 폴더에 올리면 다들 고마워했어요", 5), ("친한 사람끼리는 나눴어요", 4),
            ("각자 자기 자료만 썼어요", 2), ("자료를 감추는 분위기였어요", 1)]),
        ("item", "peer_gossip", "누군가 자리를 비우면…", [
            ("아무 일도 없었어요", 5), ("가벼운 농담 정도였어요", 4),
            ("그 사람 이야기가 시작됐어요", 2), ("다음은 내 차례일까 봐 불안했어요", 1)]),
    ]},
    {"key": "class", "title": "수업 종이 울리면", "scene": "종이 울리고, 학생들이 하나둘 들어와요.", "core": [
        ("item", "stud_motive", "학생들의 눈빛은 어땠나요?", [
            ("배우고 싶어 반짝였어요", 5), ("대체로 열심이었어요", 4),
            ("출석 때문에 앉아 있는 학생이 많았어요", 2), ("공부보다 다른 목적이 커 보였어요", 1)]),
        ("item", "teach_freedom", "오늘 수업, 내 방식대로 해 볼 수 있었나요?", [
            ("교재 밖 활동도 자유롭게 했어요", 5), ("진도만 맞추면 괜찮았어요", 4),
            ("정해진 대로만 해야 했어요", 2), ("PPT 글자 하나까지 맞춰야 했어요", 1)]),
    ], "more": [
        ("fact", "class_size", "한 반 학생은 보통 몇 명이었나요?"),
        ("item", "stud_attend", "출석을 부르면, 빈자리는요?", [
            ("거의 꽉 찼고 태도도 좋았어요", 5), ("몇 자리 비는 정도였어요", 4),
            ("절반이 비는 날도 많았어요", 2), ("휴대폰과 잠이 수업을 이겼어요", 1)]),
        ("item", "stud_respect", "학생들이 선생님을 대하는 태도는요?", [
            ("깍듯하고 따뜻했어요", 5), ("대체로 예의 있었어요", 4),
            ("가볍게 대하는 학생이 많았어요", 2), ("무례한 일이 잦았어요", 1)]),
        ("item", "stud_mix", "교실을 둘러보면, 학생들 국적은요?", [
            ("여러 나라가 섞여 한국어로만 통했어요", 5), ("꽤 다양했어요", 4),
            ("두세 나라 정도였어요", 3), ("대부분 한 나라라 모국어가 오갔어요", 1)]),
        ("item", "teach_material", "가르치는 교재와 커리큘럼은요?", [
            ("체계적이고 쓰기 좋았어요", 5), ("조금 보충하면 쓸 만했어요", 4),
            ("매번 따로 만들어야 했어요", 2), ("낡고 오류투성이였어요", 1)]),
        ("item", "teach_class", "반 인원과 레벨 편성은요?", [
            ("인원도 수준도 딱 맞았어요", 5), ("가끔 섞이지만 괜찮았어요", 4),
            ("같은 반인데 수준 차이가 컸어요", 2), ("너무 많아서 말하기 수업이 안 됐어요", 1)]),
        ("item", "teach_grading", "학기말 승급 시험, 기준은요?", [
            ("원칙대로 지켜졌어요", 5), ("대체로 지켜졌어요", 4),
            ("학생 유지를 위해 거의 다 올렸어요", 2), ("점수를 올려 달라는 압박이 있었어요", 1)]),
    ]},
    {"key": "after", "title": "수업이 끝나도", "scene": "수업은 끝났지만, 할 일이 남아 있어요.", "core": [
        ("item", "work_admin", "수업 말고 해야 하는 일은요?", [
            ("거의 없어서 수업에만 집중했어요", 5), ("출결·성적 정리 정도였어요", 4),
            ("보고서와 서류가 수업만큼 많았어요", 2), ("행정 직원인지 교사인지 헷갈렸어요", 1)]),
    ], "more": [
        ("fact", "weekly_hours", "일주일에 강의는 몇 시간 정도였나요?"),
        ("item", "work_offhours", "밤 10시, 휴대폰이 울려요.", [
            ("그럴 일이 없었어요", 5), ("가끔 급한 공지 정도였어요", 4),
            ("단톡방 업무 지시가 일상이었어요", 2), ("주말에도 답장을 해야 했어요", 1)]),
        ("item", "work_schedule", "다음 학기 시간표가 나왔어요.", [
            ("희망이 반영되고 공평했어요", 5), ("대체로 괜찮았어요", 4),
            ("좋은 시간대는 늘 같은 사람 차지였어요", 2), ("말해도 소용없었어요", 1)]),
        ("item", "adm_help", "행정실에 부탁할 일이 생겼어요.", [
            ("빠르고 친절하게 처리해 줬어요", 5), ("시간은 걸려도 해 줬어요", 4),
            ("몇 번을 말해야 했어요", 2), ("교사를 귀찮게 여겼어요", 1)]),
        ("item", "adm_notice", "학기 일정과 공지는요?", [
            ("학기 전에 미리 정리돼 왔어요", 5), ("대체로 미리 알았어요", 4),
            ("늘 직전에 알았어요", 2), ("여러 단톡방에 흩어져 놓치기 일쑤였어요", 1)]),
        ("item", "adm_burden", "결석한 학생, 비자 서류… 누가 챙겼나요?", [
            ("행정실이 다 맡았어요", 5), ("가끔 연락 정도만 했어요", 4),
            ("출결 추적은 교사 몫이었어요", 2), ("이탈 학생 책임까지 교사에게 왔어요", 1)]),
    ]},
    {"key": "trouble", "title": "곤란한 일이 생긴 날", "scene": "어느 날, 한 학생이 성적 때문에 민원을 넣었어요.", "core": [
        ("item", "lead_protect", "그때 관리자는요?", [
            ("사실을 확인하고 내 편에 서 줬어요", 5), ("중간에서 잘 조율해 줬어요", 4),
            ("학생 쪽 말만 들었어요", 2), ("모든 책임을 나에게 돌렸어요", 1)]),
    ], "more": [
        ("item", "lead_expert", "관리자가 수업을 보고 한 말은요?", [
            ("현장을 아는 사람의 조언이었어요", 5), ("무난한 피드백이었어요", 4),
            ("현장을 잘 모르는 지적이었어요", 2), ("수업에 관심이 없었어요", 1)]),
        ("item", "lead_fair", "관리자는 모든 선생님을 똑같이 대했나요?", [
            ("누구에게나 같은 기준이었어요", 5), ("대체로 공정했어요", 4),
            ("아끼는 사람이 따로 있었어요", 2), ("사람마다 규칙이 달랐어요", 1)]),
    ]},
    {"key": "payday", "title": "월급날", "scene": "오늘은 월급날이에요. 통장을 확인해 봐요.", "core": [
        ("item", "pay_fair", "찍힌 숫자를 보고 든 생각은요?", [
            ("이 정도면 충분해!", 5), ("일한 만큼은 받았네", 4),
            ("준비 시간까지 생각하면 아쉬워", 2), ("이걸로 버틸 수 있을까…", 1)]),
        ("fact", "hourly_pay", "시간당 강사료는 어느 정도였나요?"),
    ], "more": [
        ("item", "pay_level", "다른 기관 강사료와 비교하면요?", [
            ("확실히 높은 편이에요", 5), ("비슷한 편이에요", 3),
            ("조금 낮은 편이에요", 2), ("업계 최저 수준이에요", 1)]),
        ("item", "pay_ontime", "월급이 들어온 날짜는요?", [
            ("단 하루도 늦은 적 없어요", 5), ("한두 번 늦었어요", 3),
            ("가끔 미뤄졌어요", 2), ("자주 밀렸어요", 1)]),
        ("item", "pay_extra", "시험 출제, 채점, 행사 인솔… 수당은요?", [
            ("하나하나 다 챙겨 줬어요", 5), ("일부는 줬어요", 3),
            ("대부분 무급이었어요", 2), ("당연히 할 일 취급이었어요", 1)]),
    ]},
    {"key": "semester", "title": "학기가 끝나 갈 무렵", "scene": "학기가 끝나 가요. 다음 학기 이야기가 나와요.", "core": [
        ("item", "stab_hours", "다음 학기 시수는요?", [
            ("늘 비슷하게 보장됐어요", 5), ("조금씩 바뀌어도 예상할 수 있었어요", 4),
            ("갑자기 줄어든 적이 있어요", 2), ("개강 직전까지 0시간일 수도 있었어요", 1)]),
    ], "more": [
        ("item", "stab_notice", "다음 학기 강의 배정은 언제 알았나요?", [
            ("한 달도 더 전에요", 5), ("2~3주 전에요", 4), ("개강 1주 전에요", 2), ("개강하고 나서야요", 1)]),
        ("item", "stab_legal", "4대 보험과 퇴직금은요?", [
            ("법대로 깔끔했어요", 5), ("대체로 잘 챙겨 줬어요", 4),
            ("시수를 쪼개서 피하는 느낌이었어요", 2), ("아예 없었어요", 1)]),
        ("fact", "insurance", "4대 보험은 가입돼 있었나요?"),
        ("item", "stab_renew", "재계약, 기준을 알 수 있었나요?", [
            ("기준이 공개되고 납득됐어요", 5), ("대충은 알았어요", 3),
            ("누구는 되고 누구는 안 되는 이유를 몰랐어요", 2), ("윗사람 마음이었어요", 1)]),
        ("fact", "contract", "계약은 보통 얼마 단위였나요?"),
    ]},
    {"key": "lookback", "title": "돌아보며", "scene": "이곳에서 보낸 시간을 잠깐 돌아봐요.", "core": [
        ("item", "grow_learn", "그동안 나는…", [
            ("교사로서 확실히 성장했어요", 5), ("배운 게 꽤 있어요", 4),
            ("버티는 법만 늘었어요", 2), ("소모되기만 했어요", 1)]),
    ], "more": [
        ("item", "grow_support", "연수나 학회에 가고 싶을 때는요?", [
            ("비용과 시간을 지원해 줬어요", 5), ("가는 건 허락해 줬어요", 3),
            ("눈치가 보였어요", 2), ("그런 기회 자체가 없었어요", 1)]),
        ("item", "grow_chance", "교재 개발이나 연구에 참여할 기회는요?", [
            ("원하면 누구나 할 수 있었어요", 5), ("가끔 기회가 왔어요", 4),
            ("늘 같은 사람만 했어요", 2), ("전혀 없었어요", 1)]),
        ("item", "grow_career", "이력서에 이곳을 적을 때 기분은요?", [
            ("든든한 한 줄이에요", 5), ("무난한 경력이에요", 4),
            ("굳이 설명이 필요해요", 2), ("빼고 싶어요", 1)]),
    ]},
    {"key": "epilogue", "title": "에필로그", "scene": "마지막 장면이에요. 친한 후배가 {org}에 지원하려고 해요.", "core": [
        ("item", "recommend", "후배에게 뭐라고 할까요?", [
            ("무조건 가!", 5), ("괜찮은 곳이야", 4), ("다른 곳도 같이 알아봐", 2), ("말리고 싶어", 1)]),
        ("item", "overall_sat", "한마디로, 이곳은…", [
            ("좋은 기억이 더 많은 곳", 5), ("그럭저럭 괜찮았던 곳", 3),
            ("힘든 기억이 더 많은 곳", 2), ("다시 떠올리고 싶지 않은 곳", 1)]),
    ], "more": [
        ("item", "stay", "같은 조건으로 다시 제안이 온다면요?", [
            ("바로 수락!", 5), ("고민해 보고 갈 것 같아요", 4), ("웬만하면 다른 곳으로", 2), ("절대 안 가요", 1)]),
        ("item", "expect", "들어오기 전 기대와 비교하면요?", [
            ("기대보다 훨씬 좋았어요", 5), ("기대만큼이었어요", 3),
            ("기대보다 아쉬웠어요", 2), ("속은 기분이었어요", 1)]),
    ]},
]

# The ending card, like a quiz result: the best and worst remembered area.
AREA_TYPES: dict[str, tuple[str, str]] = {
    "overall": ("좋은 기억이 많은 곳", "힘든 기억이 많은 곳"),
    "pay": ("월급날이 기다려지는 곳", "월급날엔 한숨이 나오는 곳"),
    "stability": ("다음 학기 걱정이 없는 곳", "다음 학기가 늘 불안한 곳"),
    "workload": ("수업에만 집중할 수 있는 곳", "수업 말고도 할 일이 많은 곳"),
    "culture": ("마음 편히 말할 수 있는 곳", "눈치가 필요한 곳"),
    "leaders": ("든든한 관리자가 있는 곳", "관리자가 아쉬운 곳"),
    "peers": ("동료 복이 있는 곳", "혼자 버텨야 하는 곳"),
    "teaching": ("가르치는 맛이 나는 곳", "수업이 답답한 곳"),
    "growth": ("교사로 성장하는 곳", "성장이 멈추는 곳"),
    "students": ("학생들이 반짝이는 곳", "학생 지도가 쉽지 않은 곳"),
    "admin": ("행정이 든든한 곳", "행정이 교사 몫인 곳"),
    "facilities": ("시설이 쾌적한 곳", "시설이 아쉬운 곳"),
    "location": ("출근길이 가벼운 곳", "출근길이 고된 곳"),
}

MAX_ORG = 80
MAX_COMMENT = 1000

ITEM_KEYS = {item for _, _, items in AREAS for item, _ in items}
FACT_OPTIONS = {key: options for key, _, options in FACTS}


def _question(q: tuple) -> dict:
    if q[0] == "fact":
        return {"fact": q[1], "q": q[2], "options": [{"text": o} for o in FACT_OPTIONS[q[1]]]}
    return {"item": q[1], "q": q[2], "options": [{"text": t, "score": s} for t, s in q[3]]}


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
