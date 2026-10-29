# 데이터 모델 (SQLite 테이블 정리)

이 프로젝트는 수집한 한국어 교원 채용공고를 단일 SQLite 파일에 저장합니다.

- **DB 파일**: `jobs.sqlite3` (프로젝트 루트, `collect_jobs.py`/`review_ui.py` 모두 `--db`로 변경 가능)
- **저널 모드**: WAL (`PRAGMA journal_mode=WAL`) → 실행 중 `jobs.sqlite3-wal`, `jobs.sqlite3-shm` 파일이 함께 생김
- **스키마 생성 위치**: `collect_jobs.py:130` `init_db()` — 실행할 때마다 `CREATE TABLE IF NOT EXISTS` + `ensure_column()`으로 마이그레이션
- **버전 관리**: `jobs.sqlite3`은 `.gitignore` 대상 (수집으로 재생성되는 데이터이지 소스가 아님)

테이블은 5개입니다.

| 테이블 | 역할 | 수명 |
| --- | --- | --- |
| `jobs` | 수집된 공고 본체 | 마감일 지나면 삭제 (`--active-only`) |
| `geocode_cache` | 장소명 → 좌표 변환 캐시 | 영구 |
| `collection_runs` | 수집 실행 1회당 1행 (통계) | 영구 |
| `source_errors` | 소스별 수집 실패 로그 | 영구 |
| `discovery_state` | ID 순차 탐색 소스의 마지막 스캔 위치 | 소스당 1행 |

---

## 1. `jobs` — 공고 본체

수집된 공고 한 건이 한 행입니다. 화면(검토 UI·지도)에 보이는 데이터는 전부 이 테이블에서 나옵니다.

| 컬럼 | 타입 | 제약 | 설명 |
| --- | --- | --- | --- |
| `job_id` | INTEGER | PK, AUTOINCREMENT | 내부 식별자 |
| `title` | TEXT | NOT NULL | 공고 제목 |
| `institution_name` | TEXT | | 채용 기관명. 지오코딩 검색어로도 사용 |
| `source_name` | TEXT | NOT NULL | 설정 파일의 소스 이름 (`sources.json` / `monitor_sources.json`의 `name`) |
| `source_url` | TEXT | NOT NULL | 공고를 발견한 목록·검색 페이지 URL |
| `original_url` | TEXT | NOT NULL | 공고 원문 URL. 중복 판정과 재확인(`--refresh`)의 기준 |
| `location_text` | TEXT | | 본문에서 추론한 지역 (주로 시·도 수준) |
| `deadline` | TEXT | | `YYYY-MM-DD` 또는 상시모집을 뜻하는 `"rolling"` |
| `posted_at` | TEXT | | 게시일 `YYYY-MM-DD` (등록일/작성일/게시일 파싱) |
| `collected_at` | TEXT | NOT NULL | 수집 시각, UTC ISO8601 (초 단위) |
| `description` | TEXT | | 본문 요약·발췌 — 앞 4,000자 |
| `raw_text` | TEXT | | 원문 텍스트 — 앞 20,000자 (API 소스는 원본 JSON) |
| `confidence_score` | INTEGER | NOT NULL | 신뢰도 0–100. 기본값은 해당 소스의 `trust` 값 |
| `status` | TEXT | NOT NULL, 기본 `'needs_review'` | 검토 상태 (아래 참조) |
| `review_note` | TEXT | | 검토자가 남긴 메모 |
| `reviewed_at` | TEXT | | 검토 시각, UTC ISO8601 |
| `content_hash` | TEXT | NOT NULL, **UNIQUE** | 같은 행 판정 해시 (아래 참조) |
| `duplicate_group_id` | TEXT | | 출처가 달라도 같은 공고면 같은 값 (아래 "출처 간 중복") |
| `is_canonical` | INTEGER | NOT NULL, 기본 1 | 중복 묶음의 대표 행이면 1. 공개 사이트는 1만 노출 |
| `first_seen_at` | TEXT | | 처음 저장된 시각. `collected_at`과 달리 refresh로 바뀌지 않음 |
| `latitude` | REAL | | 위도 (Kakao Local API) |
| `longitude` | REAL | | 경도 |
| `address` | TEXT | | 지오코딩 결과 도로명·지번 주소 |
| `place_name` | TEXT | | 지오코딩 결과 장소명 |
| `institution_type` | TEXT | | `university`, `overseas_university`, `sejong`, `multicultural`, `kiip`, `school`, `academy`, `online`, `government`, `other` |
| `country` | TEXT | | 근무 국가 (`대한민국`, `미국` …). 온라인이면 NULL |
| `is_overseas` | INTEGER | | 해외 근무면 1 |
| `qualification` | TEXT | | 요구 자격 (`한국어교원 2급 이상`) |
| `experience_required` | TEXT | | 요구 경력 (`경력 1년 이상`) |
| `newcomer_ok` | INTEGER | | 1 신입 가능 / 0 경력 필요 / NULL 언급 없음 |
| `demo_lesson` | INTEGER | | 1 모의수업·시강 있음 / NULL 언급 없음 |
| `salary_text` | TEXT | | 급여 원문 표기 (`시간당 35,000원`) |
| `benefits` | TEXT | | 해외 공고 지원 사항 (`항공권, 숙소, 비자`) |
| `body_text` | TEXT | | 공고 본문 전체 (Claude). 게시판 메뉴·이름을 뺀 정리본. `## ` 소제목, `- ` 항목. 공개 상세의 "공고 내용" |
| `summary` | TEXT | | 2~3문장 요약. `body_text`가 없을 때와 검색 설명(meta, JSON-LD)에 씀 |
| `apply_email` | TEXT | | 접수 이메일 (규칙 또는 Claude) |
| `work_period`, `work_hours` | TEXT | | 근무 기간, 근무 요일·시간 (Claude) |
| `documents`, `how_to_apply`, `schedule`, `contact` | TEXT | | 제출 서류, 접수 방법, 전형 일정, 문의처 (Claude) |
| `attachments` | TEXT | | 공고문·양식 파일 JSON `[{"name", "url", "file"}]`. 수집·refresh 때 링크 글자가 파일명인 링크에서 추출. `file`은 `mirror_attachments()`가 내려받은 사본 경로(`files/` 기준) |
| `apply_url` | TEXT | | 가장 원본에 가까운 링크(내부용, 화면에 나가지 않음). `resolve_apply_urls()`가 매 실행 끝에 고름 |
| `apply_url_source` | TEXT | | `original` / `group` / `body` / `search` / `search_none` / `aggregator` |
| `fields_source` | TEXT | | 위 필드를 채운 방법: `rules` 또는 `llm` |
| `fields_extracted_at` | TEXT | | 필드를 채운 시각, UTC ISO8601 |

> `review_note` 이후 컬럼은 `CREATE TABLE` 본문이 아니라 `init_db()`의 `ensure_column()`으로 추가됩니다.
> 기존 DB도 다음 실행 때 자동으로 `ALTER TABLE` 되고, `first_seen_at`은 비어 있으면 `collected_at`으로 채웁니다.
> 구조화 필드 목록은 `collect_jobs.py`의 `JOB_FIELD_COLUMNS`가 기준입니다.

### `status` 값

| 값 | 의미 | 설정 주체 |
| --- | --- | --- |
| `needs_review` | 수집 직후 기본 상태 | 수집기 |
| `approved` | 사람이 확인해 채택 | 검토 UI (`PATCH /api/jobs/<id>`) |
| `rejected` | 사람이 확인해 제외 | 검토 UI |

검토 UI는 이 세 값만 허용합니다. refresh·지오코딩·필드 추출은 `status != 'rejected'`인 공고만 다룹니다.
같은 공고가 다시 수집되어도 `status`, `review_note`, `reviewed_at`은 덮어쓰지 않습니다.

### 같은 행 판정 (`content_hash`)

`make_content_hash()`:

```
stable = normalize(제목) | normalize(기관명) | 마감일
제목이 비었거나 마감일이 없으면  →  stable + | normalize(URL)
content_hash = sha256(stable)
```

`normalize()`는 영숫자 외 문자를 제거하고 소문자화하므로, 공백·기호·대소문자만 다른 제목은 같은 해시가 됩니다.

저장은 `save_job()`에서 수동 upsert로 처리합니다.

1. `content_hash` 또는 `original_url`이 일치하는 기존 행을 찾음 (해시 일치를 우선)
2. 있으면 → 나머지 같은 해시·URL 행을 DELETE한 뒤 그 행을 UPDATE (`"updated"` 반환). 검토 컬럼과 `first_seen_at`은 유지
3. 없으면 → INSERT (`"saved"` 반환), `first_seen_at` 기록

`--refresh` 경로에서는 `original_url`, `deadline`, `collected_at`, `description`, `raw_text`, `content_hash`,
`duplicate_group_id`만 갱신합니다. 제목·기관명·위치는 최초 수집 시 정제된 값을 유지합니다.

### 출처 간 중복 (`duplicate_group_id`, `is_canonical`)

`content_hash`는 제목이 조금만 달라도 다른 값이 되므로, 같은 공고가 여러 게시판에 올라오면 따로 저장됩니다.
매 실행 끝에 `assign_duplicate_groups()`가 다시 묶습니다.

```
기관명 핵심 = 기관명 또는 제목에서 처음 나오는 "…대학교/…대학" (없으면 정규화한 기관명)
마감일이 날짜이고 기관명 핵심이 있으면  →  group = sha256(기관명 핵심|마감일)[:16]
그 외(마감일 없음·상시)                →  group = content_hash[:16]  (자기 자신만)
```

묶음마다 `approved` 행 → `confidence_score` 높은 행 → `first_seen_at` 이른 행 순으로 하나만 `is_canonical = 1`입니다. 행은 지우지 않습니다.

### 삭제 규칙

기본 실행(`--include-expired` 없이)에서는 `prune_inactive_jobs()`가 실행 시작과 끝에 다음을 **물리적으로 삭제**합니다.

- 마감일이 오늘보다 이전인 공고
- 마감일이 없는(NULL) 공고 중 게시일(`posted_at`, 없으면 `first_seen_at`)로부터 45일(`UNDATED_GRACE_DAYS`)이 지난 것

`deadline == "rolling"`은 남습니다. 또 실행마다 `purge_retired_sources()`가 `monitor_sources.json`의 `retired_sources`에 있는 출처 이름으로 저장된 행을 지웁니다.

즉 `jobs`는 이력 테이블이 아니라 "현재 유효한 공고" 스냅샷입니다. 실행 이력이 필요하면 `collection_runs`를 보세요.

---

## 2. `geocode_cache` — 좌표 변환 캐시

Kakao Local API 호출 결과를 검색어 단위로 캐싱합니다.

| 컬럼 | 타입 | 제약 | 설명 |
| --- | --- | --- | --- |
| `query` | TEXT | PK | 검색어 (보통 `institution_name`) |
| `latitude` | REAL | | 위도. **실패 시 NULL** |
| `longitude` | REAL | | 경도 |
| `address` | TEXT | | 도로명 주소 (없으면 지번) |
| `place_name` | TEXT | | 장소명 |
| `looked_up_at` | TEXT | NOT NULL | 조회 시각, UTC ISO8601 |

- 실패(미검색)도 좌표 NULL로 캐싱합니다 → 못 찾는 이름을 매 실행마다 재조회하지 않기 위함
- `INSERT OR REPLACE`로 갱신하므로, 다시 조회하게 하려면 해당 행을 지우면 됩니다
- `KAKAO_REST_API_KEY` 환경변수(`secrets.env`)가 없으면 지오코딩 단계 자체를 건너뜁니다
- 검색 순서: 기관명 → 지역 폴백 검색어, 각각 키워드 검색 → 주소 검색

---

## 3. `collection_runs` — 실행 기록

수집 실행 1회당 1행. `start_run()`이 시작 시 INSERT하고 `finish_run()`이 종료 시 통계를 UPDATE합니다.

| 컬럼 | 타입 | 제약 | 설명 |
| --- | --- | --- | --- |
| `run_id` | INTEGER | PK, AUTOINCREMENT | 실행 번호 |
| `started_at` | TEXT | NOT NULL | 시작 시각 UTC |
| `finished_at` | TEXT | | 종료 시각 UTC. **NULL이면 중단된 실행** |
| `candidates` | INTEGER | NOT NULL, 기본 0 | 검사한 후보 수 |
| `saved` | INTEGER | NOT NULL, 기본 0 | 신규 저장 |
| `updated` | INTEGER | NOT NULL, 기본 0 | 기존 공고 갱신 |
| `skipped` | INTEGER | NOT NULL, 기본 0 | 필터로 제외 |
| `failed` | INTEGER | NOT NULL, 기본 0 | 오류 발생 (상세는 `source_errors`) |

`review_ui.py`의 `/api/summary`가 최신 1행을, `/api/runs`가 목록을 반환합니다.

---

## 4. `source_errors` — 실패 로그

수집 중 예외가 난 소스·URL을 기록합니다 (`log_error()`, `collect_jobs.py:870`).

| 컬럼 | 타입 | 제약 | 설명 |
| --- | --- | --- | --- |
| `error_id` | INTEGER | PK, AUTOINCREMENT | |
| `run_id` | INTEGER | | `collection_runs.run_id`를 가리킴 (FK 제약은 없음) |
| `source_name` | TEXT | | 소스 이름 |
| `source_url` | TEXT | | 실패한 URL |
| `message` | TEXT | NOT NULL | 예외 메시지, **1,000자로 잘림** |
| `created_at` | TEXT | NOT NULL | 발생 시각 UTC |

정리(purge) 로직이 없으므로 계속 누적됩니다.

---

## 5. `discovery_state` — 순차 ID 탐색 위치

`hackers_mobile_probe`처럼 게시글 번호를 1씩 올려가며 훑는 소스가 어디까지 봤는지 기억합니다.

| 컬럼 | 타입 | 제약 | 설명 |
| --- | --- | --- | --- |
| `source_name` | TEXT | PK | 소스 이름 |
| `last_id` | INTEGER | NOT NULL | 마지막으로 확인한 게시글 번호 |
| `updated_at` | TEXT | NOT NULL | 갱신 시각 UTC |

`ON CONFLICT(source_name) DO UPDATE`로 upsert 합니다 (`collect_jobs.py:224`).
덕분에 `monitor_sources.json`의 `id_end`를 수동으로 계속 늘려줄 필요가 없습니다.
처음부터 다시 훑고 싶으면 해당 행을 삭제하세요.

---

## 테이블 간 관계

```
collection_runs (run_id)
      │  1:N
      └──< source_errors (run_id)          -- FK 제약 없음, 값만 참조

jobs ── institution_name / 지역 폴백 검색어 ──> geocode_cache (query)
                                               -- FK 아님, 결과를 jobs에 복사

discovery_state (source_name) ~ jobs.source_name   -- 이름으로만 느슨하게 연결
```

외래 키 제약은 어디에도 선언되어 있지 않습니다 (`PRAGMA foreign_keys`도 켜지 않음).
테이블 간 연결은 값의 일치로만 유지됩니다.

인덱스는 SQLite가 PK/UNIQUE 때문에 자동 생성하는 것뿐입니다:
`sqlite_autoindex_jobs_1` (`content_hash` UNIQUE), `sqlite_autoindex_discovery_state_1` (`source_name` PK).
`jobs.original_url`, `jobs.status`, `jobs.source_name`은 조회에 자주 쓰이지만 인덱스가 없습니다 (현재 데이터 규모에서는 문제 없음).

---

## 데이터를 읽는 쪽

`review_ui.py`(로컬 검토 서버)가 이 테이블들을 읽습니다.

| 엔드포인트 | 사용 테이블 | 비고 |
| --- | --- | --- |
| `GET /api/jobs` | `jobs` | `q`(제목·기관·위치·본문 LIKE), `status`, `source` 필터. `limit` 기본 200 / 최대 500. 마감 임박순 → 최근 수집순 정렬 |
| `PATCH /api/jobs/<id>` | `jobs` | `status`, `review_note`, `reviewed_at` 갱신 |
| `GET /api/summary` | `jobs`, `collection_runs` | 총건수, 상태별·소스별 집계, 최근 실행 1건 |
| `GET /api/runs` | `collection_runs` | 실행 이력 |
| `GET /api/config` | — | 지도용 Kakao JS 키 전달 |

`GET /api/jobs`는 기본으로 마감된 공고를 빼고 반환합니다(`include_expired=1`이면 포함).
반환 컬럼은 `review_ui.py`의 `JOB_COLUMNS`가 기준이며, 구조화 필드와 `is_canonical`도 포함합니다.

---

## 유용한 쿼리

```sql
-- 상태별 건수
SELECT status, COUNT(*) FROM jobs GROUP BY status ORDER BY 2 DESC;

-- 소스별 건수
SELECT source_name, COUNT(*) FROM jobs GROUP BY source_name ORDER BY 2 DESC;

-- 마감 임박 (상시모집 제외)
SELECT deadline, title, institution_name
FROM jobs
WHERE deadline != 'rolling' AND deadline >= date('now')
ORDER BY deadline
LIMIT 20;

-- 좌표가 아직 없는 공고
SELECT job_id, institution_name, location_text
FROM jobs WHERE latitude IS NULL;

-- 지오코딩에 실패해 캐시된 검색어
SELECT query, looked_up_at FROM geocode_cache WHERE latitude IS NULL;

-- 중단된 실행 (finished_at NULL)
SELECT run_id, started_at FROM collection_runs WHERE finished_at IS NULL;

-- 최근 실패 로그
SELECT created_at, source_name, message
FROM source_errors ORDER BY error_id DESC LIMIT 20;
```

---

## 정리 메모

- 루트의 `database.db`(0바이트)는 어느 코드도 참조하지 않는 빈 파일입니다. 실제 DB는 `jobs.sqlite3` 하나뿐이며, `database.db`는 삭제해도 됩니다 (현재 `.gitignore`에 없어 그대로 두면 커밋될 수 있음).
- `raw_text`(공고당 최대 20KB)가 DB 용량의 대부분을 차지합니다. 재파싱이 필요 없다면 승인 완료된 공고의 `raw_text`를 비워 용량을 줄일 수 있습니다.
- `source_errors`는 무한 누적되므로 주기적 정리를 고려하세요.
