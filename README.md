# Korean Teaching Job Collector

한국어학당, 한국어교원, 한국어 강사 관련 채용정보(국내·해외)를 수집해 SQLite DB에 저장하는 수집 엔진입니다.

## 빠른 실행

```powershell
python collect_jobs.py --sample
```

샘플 HTML을 읽어 `jobs.sqlite3`에 공고를 저장합니다.

실제 출처를 수집하려면 네트워크 접근이 가능한 환경에서 실행합니다.

```powershell
python collect_jobs.py
```

테스트:

```powershell
python -m unittest discover -s tests
```

## 출처 정책

이 데이터는 광고가 붙는 공개 사이트에 쓰일 예정이라, 출처는 다음 기준으로 고릅니다.

- **원래 공고를 낸 기관과 공공 게시판을 우선**합니다 (국립국어원, 세종학당재단, 누리 세종학당, 국제한국어교육학회, 대학 공지, 다누리).
- **로그인 장벽을 우회하지 않습니다.** 회원 전용 페이지는 수집하지 않습니다.
- **다른 회사가 모아 둔 채용 DB를 다시 모으지 않습니다** (상업 채용포털·재게시 사이트).
- 공개 사이트에는 원문 전문 대신 **사실 정보(제목·기관·마감일·원문 링크)와 직접 만든 요약**만 노출합니다. `raw_text`는 내부 파싱용입니다.

`monitor_sources.json`의 `retired_sources`에 중단한 출처와 이유가 적혀 있습니다. 실행할 때마다 이 출처들에서 예전에 저장된 공고를 DB에서 지웁니다(`removed N jobs from retired sources`).

| 중단한 출처 | 이유 |
| --- | --- |
| 하이브레인넷 | 상세 공고가 회원 전용. 로그인 수집은 이용약관·DB 권리 침해 소지 |
| 해커스학점은행 | 목록이 로그인 전용이라 게시글 번호를 순차 탐색하던 방식. 경쟁사이기도 함 |
| 잡코리아, 인크루트 | 상업 채용포털의 DB 재수집 |
| 진학프로 | 다른 게시판 공고의 재게시. `--jinhakpro-pages N`으로 명시적으로 켤 수 있음 |

`seed_urls.txt`에서 이 출처들의 줄은 `# retired …`로 주석 처리했습니다.

**한국어교육바다(KLEOcean)**는 한국어교육 커뮤니티의 재게시 게시판이지만, 현재 해외 공고를 얻을 수 있는 거의 유일한 출처라서 유지합니다. 해외 대학 공식 채용 페이지를 직접 수집하는 출처로 대체하는 것을 권장합니다.

## 수집 동작

기본 실행은 오늘 기준으로 접수 기간이 유효한 공고만 저장합니다.

- 마감일이 지난 공고는 저장하지 않고, DB에 남은 것도 실행 시작과 끝에 정리합니다.
- **마감일을 읽지 못한 공고는 버리지 않고** 게시일(없으면 처음 본 날)로부터 45일간 검토 대상으로 둡니다(`UNDATED_GRACE_DAYS`). 해외 공고는 마감일이 영어·일본어로 적혀 있거나 아예 없는 경우가 많아, 예전처럼 버리면 대부분 사라졌습니다.
- 마감일 파싱은 한국어(`접수기간 … ~ …`, `마감일 :`), 영어(`Application deadline: November 15, 2026`, `Review of applications will begin on December 1`, `Next review date: Monday, Nov 2, 2026`), 일본어·중국어(`応募締切 2026年11月30日`, `截止日期`)를 읽습니다. `until the position is filled`와 `채용 시까지`는 상시모집(`rolling`)입니다.
- 날짜 앞에 `~`만 있는 경우는 바로 앞 문맥이 접수·모집·지원·제출일 때만 마감일로 봅니다.

지난 공고까지 포함해 조사하려면 명시적으로 옵션을 켭니다.

```powershell
python collect_jobs.py --include-expired
```

같은 호스트에는 요청 사이에 최소 1초 간격을 둡니다(`MIN_REQUEST_INTERVAL`). 인증서 체인이 불완전한 대학 사이트는 검증 없이 다시 요청하되, `warning: TLS verification skipped for …`를 남깁니다.

누리 세종학당 한국어 교원 모집 목록은 최대 126페이지까지 확인할 수 있습니다. 한 페이지 전체가 지난 공고이면 더 오래된 페이지는 자동으로 멈춥니다.

```powershell
python collect_jobs.py --nuri-pages 20
```

`seed_urls.txt`에 찾은 채용공고 URL을 추가하면 상세 페이지를 직접 수집합니다. 한 줄은 상세 페이지 URL 1개당 공고 1건입니다 — 목록을 순회하며 새 공고를 찾아주지 않습니다. 이미 DB에 저장된 URL은 다시 요청하지 않습니다.

기존에 저장된 공고는 실행마다 `original_url`을 다시 불러와 마감일 연장·조기 마감 여부를 갱신합니다(`refresh_existing_jobs`). 제목·기관·지역은 건드리지 않고 마감일과 본문만 새로고침하며, `rejected` 상태인 공고는 제외합니다. `--no-refresh`로 끌 수 있습니다.

```csv
url,source_name,confidence_score,kind,title_hint,institution_hint,location_hint,deadline_hint
```

### 자동 탐색 출처 (`monitor_sources.json`)

- `kteacher_list`: 국립국어원 한국어교원 구인정보처럼 목록이 로그인 없이 열리는 게시판. 페이지 단위로 순회하며 지난 공고만 있는 페이지에서 멈춥니다. `국외` 분류는 해외 공고로 들어옵니다.
- `iakle_list`: 국제한국어교육학회 게시판(POST AJAX 전용).
- `generic_links` (또는 `kind` 생략): 페이지의 `<a>` 링크 중 관련 있어 보이는 것만 골라 상세 페이지를 엽니다. `url`에 `{page}`를 넣으면 `pages` 수만큼 순회하고, 연속 3페이지가 0건이면 멈춥니다. 게시판 자기 자신을 가리키는 링크(필터 탭·페이지 이동)는 건너뜁니다.
- `hackers_mobile_probe`, `jobkorea_mobile_list`: 코드는 남아 있지만 현재 쓰는 출처가 없습니다.

### 위치·기관명

- **위치**는 페이지 푸터(사이트 운영사 주소)를 잘라낸 뒤, `근무지/근무지역/소재지` 같은 항목을 먼저 보고, 다음으로 `주소`, 시·도 정식 명칭, 단독으로 쓰인 지역명 순으로 찾습니다. `경기도 광주시`는 `광주`가 아니라 `경기`입니다. `세종학당`, `서울대학교`, `해외여행에 결격사유` 같은 단어는 지역으로 보지 않습니다.
- **기관명**을 못 찾으면 출처 이름으로 대신하지 않고 비워 둡니다(예전에는 `하이브레인넷 한국어 채용검색`이 기관명으로 들어가 지도에 하이브레인넷 사무실이 찍혔습니다). 제목의 `[기관명]`을 대신 쓰되 `[공고]`, `[홍보]` 같은 말머리는 건너뜁니다.

### 중복 공고

같은 공고가 여러 게시판에 올라오면 **기관명 핵심(예: `아주대학교`) + 같은 마감일**로 묶습니다(`assign_duplicate_groups`). 행은 지우지 않고 `duplicate_group_id`를 같게 하고, 그중 하나만 `is_canonical = 1`입니다(승인된 행 → 신뢰도 높은 출처 → 먼저 본 행 순). 공개 사이트는 `is_canonical = 1`만 보여 주면 됩니다.

다시 수집된 공고는 검토 상태(`status`, `review_note`, `reviewed_at`)와 `first_seen_at`을 그대로 유지합니다.

## 구조화 필드 (`extract_fields.py`)

수집이 끝나면 공고마다 다음 필드를 채웁니다.

| 필드 | 예 |
| --- | --- |
| `institution_type` | `university`, `overseas_university`, `sejong`, `multicultural`, `kiip`, `school`, `academy`, `online`, `government`, `other` |
| `country`, `is_overseas` | `미국`, `1` |
| `qualification` | `한국어교원 2급 이상` |
| `experience_required` | `경력 1년 이상` |
| `newcomer_ok` | `1` 신입 가능 / `0` 경력 필요 / `NULL` 언급 없음 |
| `demo_lesson` | `1` 모의수업 있음 / `NULL` 언급 없음 |
| `salary_text` | `시간당 35,000원` |
| `benefits` | 해외 공고의 `항공권, 숙소, 비자` |
| `summary` | 원문을 베끼지 않은 요약 |

기본은 **정규식 규칙**(무료)으로 채웁니다. 요약은 사실 정보를 이어 붙인 한 줄입니다.

`--llm-fields`를 켜면 아직 규칙으로만 채워진 공고를 **Claude(`claude-opus-5-5`)**로 보내 빈 필드를 채우고, 원문을 베끼지 않은 2~3문장 요약을 만듭니다. 공고마다 한 번만 보내고, 실행당 최대 `--llm-limit`건(기본 50)입니다. API 사용료가 발생합니다.

```powershell
pip install anthropic
$env:ANTHROPIC_API_KEY="sk-ant-..."   # 또는 secrets.env에 ANTHROPIC_API_KEY=...
python collect_jobs.py --llm-fields --llm-limit 20
```

키가 없거나 거부되면 첫 요청에서 멈추고 규칙 결과를 그대로 둡니다. 안전 분류기가 요청을 거절하면 서버가 다른 모델로 다시 시도하도록 `fallbacks: "default"`를 켜 두었습니다.

## 주요 파일

- `collect_jobs.py`: 수집 CLI
- `extract_fields.py`: 구조화 필드 추출(규칙 + 선택적 Claude)
- `review_ui.py`: 수집된 공고를 확인하는 로컬 UI 서버
- `ui/`: 검토 UI 정적 파일
- `tests/`: 파서·DB 규칙 회귀 테스트 (`python -m unittest discover -s tests`)
- `sources.json`: 키워드, 포함/제외어 설정
- `monitor_sources.json`: 자동 탐색 출처 목록과 중단한 출처(`retired_sources`)
- `seed_urls.txt`: 사람이 직접 등록하는 상세 페이지 URL 목록(1줄 = 공고 1건)
- `jobs.sqlite3`: 실행 후 생성되는 SQLite DB
- `sample_jobs.html`: 로컬 검증용 샘플 공고
- `secrets.env`: API 키(gitignore 대상). `secrets.env.example`을 복사해서 사용

사람인 API 키가 있으면 같은 명령에서 사람인 수집도 함께 실행됩니다.

```powershell
$env:SARAMIN_ACCESS_KEY="발급받은_access_key"
python collect_jobs.py --saramin-count 50
```

## 검토 UI

```powershell
python review_ui.py --port 8765
```

브라우저에서 `http://127.0.0.1:8765`를 열면 수집된 공고, 출처별 통계, 최근 수집 실행 기록, 오류 로그를 볼 수 있습니다. 공고마다 구조화 필드 한 줄과 요약이 보이고, 중복 공고는 흐리게 표시됩니다. 마감된 공고는 기본으로 숨기며 `마감 공고 포함`으로 볼 수 있습니다.

각 공고는 UI에서 `승인`, `제외`, `보류` 상태로 바꿀 수 있고, 검토 메모를 함께 저장할 수 있습니다.

## 지도 (카카오맵)

수집한 공고를 지도에 찍습니다. developers.kakao.com에서 앱을 하나 만들고 키 2개를 `secrets.env`에 넣습니다.

```
KAKAO_REST_API_KEY=REST_API_키
KAKAO_JS_KEY=JavaScript_키
```

- **REST API 키**: 수집이 끝난 뒤 좌표를 채우는 데 씁니다(서버에서만 사용).
- **JavaScript 키**: 브라우저가 지도를 그릴 때 씁니다. 카카오 앱 설정의 **플랫폼 > Web**에 `http://127.0.0.1:8765`를 등록해야 지도가 뜹니다.

좌표는 **기관명**을 카카오 로컬 키워드 검색에 넣어 얻습니다. 기관명으로 찾으면 그 주소의 시·도로 `location_text`를 덮어씁니다 — 페이지 본문에서 추측한 지역보다 정확하기 때문입니다. 기관명 검색이 실패하면 `location_text`의 광역명을 시·도청 좌표로 대체합니다(대략적인 위치). 해외·온라인 공고는 지오코딩하지 않습니다. `--no-geocode`로 끌 수 있습니다.

조회 결과는 `geocode_cache` 테이블에 쌓이고, 못 찾은 이름도 캐시해서 같은 실패를 다시 요청하지 않습니다.

## 조사했지만 수집하지 않는 곳

- 고용24(옛 워크넷), 잡코리아, 공공강사(00gangsa.com): JS(Next.js SPA) 렌더링. 상업 포털은 출처 정책상으로도 제외.
- 인천광역시교육청 채용공고 게시판: 목록이 JS 폼 재제출로만 채워짐.
- JOBS.ac.kr: 검색 필터가 동작하지 않음.
- 바로쌤(barossam.com): 전 과목 기간제교사 게시판이라 신호 대비 잡음이 큼.
- Indeed: 이용약관상 자동 스크래핑 금지.

## 데이터 모델

테이블과 컬럼은 `DATA_MODEL.md`를 보세요.
