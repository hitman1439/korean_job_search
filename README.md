# Korean Teaching Job Collector

한국어학당, 한국어교원, 한국어 강사 관련 채용정보를 수집해 SQLite DB에 저장하는 초기 수집 엔진입니다.

## 빠른 실행

```powershell
python collect_jobs.py --sample
```

샘플 HTML을 읽어 `jobs.sqlite3`에 공고를 저장합니다.

실제 출처를 수집하려면 네트워크 접근이 가능한 환경에서 실행합니다.

```powershell
python collect_jobs.py
```

기본 실행은 오늘 기준으로 접수 기간이 유효한 공고만 저장합니다. 마감일이 지났거나 마감일을 확인할 수 없는 공고는 제외하고, 기존 DB에 남아 있던 비유효 공고도 정리합니다.

지난 공고까지 포함해 조사하려면 명시적으로 옵션을 켭니다.

```powershell
python collect_jobs.py --include-expired
```

누리 세종학당 한국어 교원 모집 목록은 최대 126페이지까지 확인할 수 있습니다. 유효기간 수집 모드에서는 한 페이지 전체가 지난 공고이면 더 오래된 페이지는 자동으로 멈춥니다.

```powershell
python collect_jobs.py --nuri-pages 20
```

진학프로 강사 목록도 API 키 없이 확인합니다. 목록에서 한국어 관련성이 있는 공고만 상세 페이지로 들어가 저장합니다.

```powershell
python collect_jobs.py --jinhakpro-pages 1
```

`seed_urls.txt`에 찾은 채용공고 URL을 추가하면 API 키 없이도 상세 페이지를 직접 수집합니다. 단, 한 줄은 상세 페이지 URL 1개당 공고 1건만 가져옵니다 — 목록을 순회하며 새 공고를 찾아주지 않으므로, 새 공고를 발견하면 사람이 직접 한 줄씩 추가해야 합니다. 이미 DB에 저장된 URL은 seed 단계에서 다시 요청하지 않습니다 — 같은 줄을 지우지 않고 계속 남겨둬도 매번 재수집하지 않습니다.

기존에 저장된 공고는 seed 파일과 별개로, 실행마다 DB에 있는 `original_url`을 직접 다시 불러와 마감일 연장·조기 마감 여부를 갱신합니다(`refresh_existing_jobs`). 제목·기관·지역처럼 이미 확인해 둔 값은 건드리지 않고 마감일과 본문만 새로고침하며, `거절` 상태인 공고는 대상에서 제외합니다. 매 실행마다 저장된 공고 수만큼 요청이 나가므로 느려지면 `--no-refresh`로 끌 수 있습니다.

```csv
url,source_name,confidence_score,kind,title_hint,institution_hint,location_hint,deadline_hint
```

`title_hint` 이후 값은 비워도 되지만, 검색으로 이미 확인한 값이 있으면 넣는 편이 데이터 품질이 좋습니다.

목록 페이지가 로그인 없이 안 열리지만 상세 페이지 URL은 순번(id)으로 예측 가능한 사이트(예: 해커스학점은행 `job_view.php?wr_id=`)는 `monitor_sources.json`에 등록하면 사람이 URL을 일일이 추가하지 않아도 자동으로 새 공고를 찾습니다.

목록 페이지 자체가 로그인 없이 열리는 게시판(예: 국립국어원 한국어교원 구인정보)은 `kind: "kteacher_list"`로 등록하면 페이지 단위로 순회하며 마감 지난 공고만 있는 페이지를 만나면 자동으로 멈춥니다. 단순히 페이지의 `<a>` 링크를 훑어서 관련 있어 보이는 것만 골라내면 되는 게시판(예: 세종학당재단, 대학 재게시 게시판)은 `kind`를 생략하거나 `"generic_links"`로 등록합니다.

```json
{
  "sources": [
    {
      "name": "해커스학점은행 채용정보",
      "url": "https://m.hackershakjum.com/korean/sub/job_view.php?wr_id={id}",
      "trust": 62,
      "kind": "hackers_mobile_probe",
      "id_start": 4480
    },
    {
      "name": "국립국어원 한국어교원 구인정보",
      "url": "https://kteacher.korean.go.kr/jobsearch/list",
      "trust": 88,
      "kind": "kteacher_list",
      "pages": 20
    },
    {
      "name": "세종학당재단 채용정보",
      "url": "https://www.ksif.or.kr/cop/bbs/selectBoardList.do?bbsId=BBSMSTR_000000000001",
      "trust": 90,
      "kind": "generic_links"
    },
    {
      "name": "동신대학교 국제한국어학과 재게시",
      "url": "https://korean.dsu.ac.kr/korean/index.php?pCode=news",
      "trust": 70,
      "kind": "generic_links"
    },
    {
      "name": "한국어교육바다(KLEOcean) 채용공고",
      "url": "https://kleocean.com/%ed%95%9c%ea%b5%ad%ec%96%b4%ea%b5%90%ec%9b%90-%ea%b5%ad%eb%82%b4%ec%99%b8-%ec%b1%84%ec%9a%a9%ea%b3%b5%ea%b3%a0/",
      "trust": 80,
      "kind": "generic_links"
    },
    {
      "name": "다누리 가족센터 채용정보",
      "url": "https://liveinkorea.kr/web/lay1/bbs/S1T10C29/A/6/list.do?condition=&keyword=&cat=&area=&area_detail=&search_year=&search_month=&search_recruit_stat=&rows=10&cpage={page}",
      "trust": 80,
      "kind": "generic_links",
      "pages": 5
    },
    {
      "name": "인크루트 한국어강사 검색",
      "url": "https://job.incruit.com/jobdb_list/searchjob.asp?col=job_all&il=y&kw=%ED%95%9C%EA%B5%AD%EC%96%B4%EA%B0%95%EC%82%AC",
      "trust": 60,
      "kind": "generic_links"
    }
  ]
}
```

`hackers_mobile_probe`는 `id_start`부터 번호를 하나씩 올려가며 확인하다가, 공고가 없는 번호가 25회 연속되면 멈춥니다. 마지막으로 확인한 번호는 DB(`discovery_state` 테이블)에 저장되어, 다음 실행부터는 그 지점 근처부터 이어서 스캔합니다 — `id_end`를 수동으로 계속 늘려줄 필요가 없습니다. 다른 설정 파일을 쓰려면 `--discovery-file`로 경로를 지정합니다.

`generic_links`는 `url`에 `{page}`를 넣으면 `pages` 수만큼 페이지를 순회합니다(예: `cpage={page}`). 한 페이지에 관련 공고가 0건이어도 바로 멈추지 않고, **연속 3페이지**가 0건일 때만 멈춥니다 — 다누리처럼 관련 공고가 페이지마다 드문드문 나오는 게시판도 커버하기 위해서입니다. 페이지네이션 파라미터가 실제로 안 먹히는 사이트(진학프로처럼 항상 같은 내용을 돌려주는 경우)는 이전 페이지와 링크 목록이 완전히 같으면 자동으로 멈춥니다.

새로 추가한 3곳:
- **한국어교육바다(KLEOcean)**: 한국어교육 전용 커뮤니티라 잡음이 거의 없음. 국내외 채용공고를 다 다루지만, 해외 대학 공고는 마감일이 영어로 적혀있어 국문 정규식으로 못 뽑아내는 경우가 있어 일부만 저장됩니다.
- **다누리 가족센터 채용정보**: 전국 다문화가족지원센터/건강가정지원센터 채용을 모아둔 정부 포털 게시판. 실제로는 대부분 사회복지사·상담원 채용이라 한국어 강사 공고 비중은 낮지만(5페이지 중 1건 수준), 정식 게시판이라 안전하게 걸어둠.
- **인크루트 한국어강사 검색**: 검색 키워드가 완전히는 안 먹히지만 어느 정도 관련도순으로 나오고, 서버가 목록을 그대로 내려줘서(SPA 아님) 자동화 가능.

`generic_links`는 게시판 자기 자신을 가리키는 링크(필터 탭·페이지 이동처럼 목록 URL과 경로가 같은 링크)는 건너뜁니다. 이런 링크는 쿼리스트링에 검색 키워드가 들어 있어 관련도 검사를 통과해버리는데, 실제로 열어보면 공고가 아니라 목록 페이지라서 `진행 989건` 같은 쓰레기 레코드가 저장되기 때문입니다.

### 하이브레인넷 (로그인 필요)

`하이브레인넷 한국어 채용검색`은 목록 페이지는 로그인 없이 열리지만, **개별 공고 상세 페이지 대부분이 비회원에게 401 Unauthorized를 돌려줍니다.** 한국어 키워드 진행중 공고 25건을 확인해본 결과 5건만 비회원에게 열려 있었고, 정작 우리가 원하는 `웅지세무대학교 국제교육원 한국어 강사 모집`, `동아보건대학교 한국어교육원 한국어강사 모집` 같은 공고는 전부 막혀 있었습니다. 즉 로그인 없이는 이 출처에서 실질적으로 건질 게 없습니다.

그래서 하이브레인넷 요청만 로그인 세션을 태웁니다. 계정 정보는 저장소에 들어가지 않도록 `secrets.env`에서 읽습니다. 이 파일은 `.gitignore`에 등록돼 있어 커밋되지 않습니다.

```
# secrets.env
HIBRAIN_USERID=아이디
HIBRAIN_PASSWD=비밀번호
```

`secrets.env.example`을 복사해서 값만 채우면 됩니다. 이후에는 평소대로 실행하면 됩니다.

```powershell
python collect_jobs.py
```

`secrets.env` 대신 셸 환경변수(`$env:HIBRAIN_USERID`)를 써도 되고, 둘 다 있으면 환경변수가 우선합니다. 다른 경로의 파일을 쓰려면 `--secrets`로 지정합니다. 같은 파일에 `SARAMIN_ACCESS_KEY`도 함께 넣어둘 수 있습니다.

동작 방식은 브라우저와 같습니다 — `/logins/signin`을 GET해서 세션 쿠키를 받고, 같은 주소로 `userid`/`passwd`/`isAutoSignin`을 form POST한 뒤, 그 쿠키를 하이브레인넷 요청에 계속 사용합니다. 로그인은 프로세스당 한 번만 수행하고 결과를 재사용합니다.

환경변수가 없으면 로그인을 시도하지 않고 비회원으로 접근하며, 아이디/비밀번호가 틀리면 `hibrain login rejected` 한 줄만 남기고 **나머지 출처 수집은 그대로 진행**합니다. 어느 쪽이든 막힌 공고는 `source_errors`에 401로 기록됩니다.

하이브레인넷 상세 링크에는 목록에서의 위치(`pagekey`, `page`, `sortType`)가 쿼리로 붙어 있는데, 이 값은 새 공고가 올라올 때마다 바뀝니다. 그대로 두면 같은 공고가 매번 다른 URL로 보여 중복 저장되므로 상세 URL은 `/recruitment/recruits/{id}`만 남기고 쿼리를 떼어 저장합니다.

`sources.json`의 `sources` 배열은 원래 이 `generic_links` 방식과 같은 일을 했던 자리인데, 자동탐색 출처를 한곳(`monitor_sources.json`)에서 관리하도록 여기로 옮겼습니다. `sources.json`은 이제 키워드/포함·제외어 설정 전용입니다.

**자동화 조사했지만 아직 미구현인 곳**
- 고용24(옛 워크넷), 잡코리아(www/모바일 모두): 검색 결과가 JS(Next.js SPA)로 렌더링돼 서버 응답에 목록이 없고, 내부 API도 페이지 소스에 노출돼 있지 않습니다. 헤드리스 브라우저 없이는 자동화 어렵습니다.
- 인천광역시교육청 채용공고 게시판: 실제 게시판 URL(`selectNttList.do?mi=10996&bbsId=1774`)은 찾았지만, 목록 데이터가 JS로 폼을 다시 제출해야 채워지는 방식이라 단순 GET/POST 재현으로는 안 나옵니다.
- JOBS.ac.kr: `/?s=키워드` 검색이 키워드와 무관하게 항상 같은 결과를 보여줘서(필터링 안 됨) 신뢰하기 어렵습니다.
- 바로쌤(barossam.com): 실제로는 스크래핑 가능하지만 전국 모든 과목의 기간제교사 채용을 다루는 게시판이라 한국어 관련 공고 비중이 매우 낮고, `keyword=` 파라미터도 실제로는 필터링하지 않습니다(신호 대비 잡음이 너무 커서 보류).
- 공공강사(00gangsa.com): 이 사이트도 Next.js SPA라 서버 응답에 목록이 없습니다.
- Indeed: 이용약관상 자동 스크래핑이 금지돼 있어 처음부터 제외했습니다.
- 알바몬: 검색해보니 '한국어강사' 결과가 3건뿐이라 우선순위를 낮췄습니다(추가 조사 안 함).

사람인 API 키가 있으면 같은 명령에서 자동으로 사람인 수집도 함께 실행됩니다.

```powershell
$env:SARAMIN_ACCESS_KEY="발급받은_access_key"
python collect_jobs.py --saramin-count 50
```

## 주요 파일

- `collect_jobs.py`: 수집 CLI
- `review_ui.py`: 수집된 공고를 확인하는 로컬 UI 서버
- `ui/`: 검토 UI 정적 파일
- `sources.json`: 키워드, 포함/제외어 설정
- `monitor_sources.json`: 자동으로 새 공고를 찾아내는 출처 목록(id 순번 탐색, 게시판 목록 순회, 링크 스캔 등)
- `seed_urls.txt`: 사람이 직접 등록하는 상세 페이지 URL 목록(1줄 = 공고 1건)
- `jobs.sqlite3`: 실행 후 생성되는 SQLite DB
- `sample_jobs.html`: 로컬 검증용 샘플 공고
- `secrets.env`: 사이트 계정·API 키(gitignore 대상). `secrets.env.example`을 복사해서 사용

지도 관련 컬럼: `jobs.latitude`, `jobs.longitude`, `jobs.address`, `jobs.place_name`, 그리고 조회 캐시 `geocode_cache` 테이블

## 검토 UI

```powershell
python review_ui.py --port 8765
```

브라우저에서 `http://127.0.0.1:8765`를 열면 수집된 공고, 출처별 통계, 최근 수집 실행 기록, 오류 로그를 볼 수 있습니다.

각 공고는 UI에서 `승인`, `제외`, `보류` 상태로 바꿀 수 있고, 검토 메모를 함께 저장할 수 있습니다. 상태값은 `jobs.status`, 메모는 `jobs.review_note`, 검토 시각은 `jobs.reviewed_at`에 저장됩니다.

## 지도 (카카오맵)

수집한 공고를 지도에 찍습니다. developers.kakao.com에서 앱을 하나 만들고 키 2개를 `secrets.env`에 넣습니다.

```
KAKAO_REST_API_KEY=REST_API_키
KAKAO_JS_KEY=JavaScript_키
```

- **REST API 키**: 수집이 끝난 뒤 좌표를 채우는 데 씁니다(서버에서만 사용).
- **JavaScript 키**: 브라우저가 지도를 그릴 때 씁니다. 카카오 앱 설정의 **플랫폼 > Web**에 `http://127.0.0.1:8765`를 등록해야 지도가 뜹니다. 이 키는 브라우저에 노출되는 값이라 도메인 등록이 사실상의 보호 장치입니다.

키를 넣고 평소대로 실행하면 저장 직후 좌표를 채우고 `geocoded=N ungeocoded=N`을 출력합니다. 키가 없으면 지오코딩을 건너뛰고 나머지는 그대로 동작합니다. 좌표만 다시 채우고 싶지 않으면 `--no-geocode`로 끕니다.

```powershell
python collect_jobs.py
python review_ui.py --port 8765   # 브라우저에서 '지도' 탭
```

### 왜 기관명으로 찾는가

좌표는 `location_text`가 아니라 **`institution_name`**을 카카오 로컬 키워드 검색에 넣어 얻습니다. `location_text`는 광역 단위인 데다 실측해보니 오류가 많았습니다 — 게시 사이트 푸터의 주소를 집어서 하이브레인넷 공고 4건이 전부 `창원`(회사 소재지)으로, 여러 지방 공고가 `서울`로 잘못 붙어 있었습니다. 기관명은 `웅지세무대학교`, `동아보건대학교`처럼 실제 장소라 검색이 정확합니다.

기관명 검색이 실패하면 `location_text`의 광역명을 시·도청 좌표로 대체합니다(`REGION_FALLBACK_QUERY`). 대략적인 위치라는 뜻이므로 지도에서 시청 자리에 찍힌 마커는 그렇게 이해하면 됩니다.

조회 결과는 `geocode_cache` 테이블에 쌓입니다. 못 찾은 이름도 같이 캐시해서 매 실행마다 같은 실패를 재요청하지 않습니다. 좌표는 `jobs.latitude`/`longitude`/`address`/`place_name`에 저장되고, 이미 좌표가 있는 공고는 다시 조회하지 않습니다.

지도 탭은 목록과 같은 필터(검색어·상태·출처)를 그대로 씁니다. 좌표가 없는 공고는 지도에서 빠지며 몇 건이 빠졌는지 지도 아래에 표시됩니다.

## 데이터 모델

`jobs` 테이블은 제목, 기관명, 출처, 원문 URL, 위치, 마감일, 본문, 신뢰도 점수, 중복 해시를 저장합니다. 같은 `content_hash`가 다시 들어오면 신규 삽입 대신 기존 공고를 업데이트합니다.

## 다음 수집기 후보

- 사람인 채용정보 API: 구현됨. `SARAMIN_ACCESS_KEY` 환경변수 필요
- 하이브레인넷: 구현됨. 상세 페이지가 회원 전용이라 `HIBRAIN_USERID`/`HIBRAIN_PASSWD` 환경변수 필요
- 국립국어원 한국어교원 구인정보: 구현됨. `monitor_sources.json`의 `kteacher_list`
- 누리 세종학당 한국어 교원 모집: 구현됨. `--nuri-pages`로 수집 페이지 수 조절
- 진학프로 강사 목록: 구현됨. `--jinhakpro-pages`로 수집 페이지 수 조절
- 고용24/월드잡플러스, 잡코리아, 인천광역시교육청, 공공강사: JS 렌더링/폼 재제출 방식이라 조사는 했지만 미구현 (자세한 내용은 위 `monitor_sources.json` 절 참고)
