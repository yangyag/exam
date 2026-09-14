# back/ — 정보처리기사 필기 API (FastAPI)

`ipe` 스키마(로컬 `app` DB, 운영 EC2 는 공용 컨테이너 `yangyag-postgres` 의 `exam` DB)를 읽어 **문항 조회 · 채점 · 진도 · 과목 사이클** 을 제공하는 HTTP API 입니다.
프론트(Nuxt)가 이 문서만 보고 붙일 수 있는 수준을 목표로 하고, 더 자세한 내용은 코드와 `/openapi.json` 을 정본으로 봅니다.

전제: `ipe` 스키마에 문항이 적재돼 있어야 합니다(`db/README.md`). 접속 정보가 없거나 DB 가 내려가 있으면 **DB 를 쓰는 엔드포인트**가 2초 안에 `503` 을 돌려줍니다(`/api/health` 는 `{"status":"degraded","database":"unavailable"}`). 루트 `/` · `/docs` · `/openapi.json` · `/figures/*` 는 DB 를 쓰지 않으므로 DB 가 없어도 그대로 응답합니다(`/figures` 는 그림 디렉터리가 마운트됐을 때만 생깁니다).

**목차** — [1. 로컬 실행](#1-로컬-실행) · [테스트](#테스트) / [2. 환경변수](#2-환경변수) / [3. 엔드포인트](#3-엔드포인트) / [4. 응답 규칙](#4-응답-규칙) — [조회 응답](#조회-응답에는-정답이-없습니다) · [랜덤 중복 제거](#랜덤-출제의-중복-제거-i-01) · [응답 스키마](#응답-스키마-필드) · [채점](#채점) · [세션과 슬롯](#세션과-슬롯) · [진도 수정](#진도-상태-수정) · [오류 규약](#오류-규약) / [5. 의존 DB 객체](#5-의존-db-객체) / [6. 프론트에서 붙일 때](#6-프론트에서-붙일-때) / [7. 알아둘 것](#7-알아둘-것)

---

## 1. 로컬 실행

```bash
# 1) 의존성 설치 (최초 1회, 저장소 루트에서)
cd back
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt

# 2) DB 접속 정보 — 저장소 루트에 .env 가 있으면 자동으로 읽으므로 이 줄은 건너뜁니다
export EXAM_DB_URL='postgresql://yangyag:<비밀번호>@localhost:5432/app'

# 3) 기동
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8092 --reload
```

Linux 는 인터프리터 경로만 `.venv/bin/python` 으로, PowerShell 은 2) 를 `$env:EXAM_DB_URL='...'` 로 바꾸면 됩니다. **운영(EC2) 기동은 docker 이미지(`deploy/README.md`)** 로 하고, 다른 기기에서 접속해야 하는 개발 서버라면 `--host 0.0.0.0` 을 붙이세요(기본 예시는 `127.0.0.1`).

기동 확인:

```bash
curl http://127.0.0.1:8092/api/health
# {"status":"ok","database":"ok","dbUrlSource":"EXAM_DB_URL (.env)"}
# {"status":"ok","database":"ok","dbUrlSource":"DATABASE_URL (.env)"}   ← .env 가 DATABASE_URL 을 정의한 경우
```

**저장소 루트에 `.env` 가 없는 곳에서는 2) 를 반드시 하세요** — 새로 clone 한 저장소나 `git worktree` 에는 `.env` 가 따라오지 않습니다(gitignore). 없으면 앱이 조용히 내장 기본값 `postgresql://yangyag@localhost:5432/app`(비밀번호 없음)을 쓰고, `/api/health` 가 이렇게 나옵니다:

```
{"status":"degraded","database":"unavailable","dbUrlSource":"기본값"}
```

`dbUrlSource` 가 어느 출처를 썼는지 알려줍니다(`back/app/config.py`). `.env` 파일에서 온 값에는 출처 뒤에 ` (.env)` 가 붙으므로, 저장소 `.env` 가 `EXAM_DB_URL` 을 정의했으면 `"EXAM_DB_URL (.env)"`, `DATABASE_URL` 을 정의했으면 `"DATABASE_URL (.env)"` 이고, 셸에서 `EXAM_DB_URL` 을 직접 export 했으면 `"EXAM_DB_URL"` 입니다(`EXAM_DB_URL` → `DATABASE_URL` 순으로 먼저 있는 값을 씁니다). `기본값` 이면 2) 를 빠뜨린 것입니다.

| 주소 | 설명 |
|---|---|
| `http://127.0.0.1:8092/docs` | Swagger UI (엔드포인트를 브라우저에서 직접 호출 가능) |
| `http://127.0.0.1:8092/openapi.json` | OpenAPI 스키마 (프론트 타입 생성용) |
| `http://127.0.0.1:8092/api/health` | 헬스체크 |
| `http://127.0.0.1:8092/figures/<회차>/<번호>.png` | 문항 도식 이미지 정적 서빙 |

`--reload` 는 개발용입니다. **배포는 docker 이미지(`deploy/`, EC2)로 하며** 이 문서에서는 다루지 않습니다 — 절차는 `deploy/README.md`.

### 테스트

```bash
cd back
.venv/Scripts/python -m pytest                       # 전체 198개 = 163 + 35 (2026-09-14 기준, 정본은 plan/test-cases.md. DB 접속 정보가 없으면 통합 35개는 skip)
.venv/Scripts/python -m pytest -m "not integration"  # DB 없이 163개
.venv/Scripts/python -m pytest -m integration        # 실제 ipe DB 가 있어야 도는 35개
```

**통합 테스트에는 테스트 전용 DB 를 쓰세요.** 접속 대상은 `TEST_DB_URL`(환경변수 또는 저장소 루트 `.env`)이 있으면 그 DB, 없으면 앱과 같은 `EXAM_DB_URL`/`DATABASE_URL` 입니다(우선순위는 `back/tests/conftest.py`). 실행 첫 줄에 `통합 테스트 DB: postgresql://... (출처: TEST_DB_URL)` 처럼 어느 DB 에 붙는지 찍습니다(비밀번호는 가림).

앱 DB 로 돌리면 사이클 통합 테스트가 위험합니다 — 그 테스트들은 문항을 풀어 사이클·세션·슬롯·원장을 만들고 `과목에 사이클 기록 없음`을 전제로 하기 때문에, 앱에서 이미 쓰고 있는 과목에서는 409(진행 중 사이클)로 깨집니다. 그래서 이제는 그런 과목을 만나면 **사용자 기록을 건드리지 않고 테스트를 건너뛰면서** 이유(`require_free_subject`: 과목 상태·사이클 번호 + 해결 방법)를 남깁니다. 사용자의 진도 데이터를 지키려면 테스트 전용 DB 를 두는 편이 가장 깔끔합니다.

준비(로컬 docker 기준 — 최초 1회, 문항 데이터가 바뀌면 3)만 다시):

```bash
# 1) 테스트 DB(app_test)와 ipe 스키마. superuser 로 한 번.
docker exec -i postgres psql -U postgres -d postgres -c "CREATE DATABASE app_test OWNER yangyag"
docker exec -i postgres psql -U postgres -d app_test -c \
  "CREATE SCHEMA IF NOT EXISTS ipe AUTHORIZATION yangyag; CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA ipe"

# 2) 저장소 루트 .env 에 TEST_DB_URL 한 줄 (DB 이름만 app_test 로)
#    TEST_DB_URL=postgresql://yangyag:<비번>@127.0.0.1:5432/app_test?options=-csearch_path%3Dipe,public

# 3) 저장소 루트에서: 문항 스키마·진도 테이블과 1,300문항 적재 (멱등)
set -a; . ./.env; set +a
: "${TEST_DB_URL:?.env 에 TEST_DB_URL 을 먼저 추가하세요}"   # 실수로 앱 DB 에 적재하지 않게 막는 안전선
EXAM_DB_URL="$TEST_DB_URL" python tools/load_db.py --init
EXAM_DB_URL="$TEST_DB_URL" python tools/load_db.py          # 적재 + 검증(전부 통과)
```

`TEST_DB_URL` 을 두지 않으면 지금까지처럼 앱 DB 로 돌아갑니다(통합 테스트는 자기 행만 만들고 끝나면 지우며, 남의 사이클과 겹치는 과목은 건너뜁니다).

접속 정보가 없어 통합 테스트를 건너뛸 때는 `PGCONNECT_TIMEOUT`(5초)을 걸어 둡니다(`back/tests/conftest.py`). 없으면 `localhost` 가 IPv6(`::1`)부터 시도하면서 죽은 주소마다 OS 기본 타임아웃(약 2분)을 기다려, 통합 35건이 전부 skip 이어도 한 시간 넘게 걸립니다. 지금은 전체 실행이 **163 passed / 35 skipped / 약 78초(1분 20초)** 입니다(2026-09-14 기준, 정본은 `plan/test-cases.md`).

`pytest`·`httpx` 는 `requirements.txt` 에 들어 있어 1) 의 설치만으로 돌아갑니다. 진도 행을 만드는 통합 테스트는 끝나면 스스로 되돌리고, DB 없이 503 을 확인하는 `test_db_unavailable.py` 는 접속할 수 없는 주소(127.0.0.1:1)만 씁니다. 종료된 세션 채점 거부(`409`)는 단위(`test_grading_api.py`)와 실 DB(`test_integration_db.py`) 양쪽에서 확인합니다. 채점과 종료가 겹칠 때의 잠금 순서(`B-01`)는 실제 DB의 행 잠금을 재현하는 `test_integration_concurrency.py` 가 고정합니다(study_attempt 에 SHARE 잠금을 잠시 걸고, 세션 행 잠금은 `FOR UPDATE NOWAIT` 프로브로 판정). 과목 사이클 계약은 가짜 DB(`test_cycles_api.py`)와 실 DB(`test_integration_cycles.py`) 양쪽에서 고정합니다 — 라운드 자동 전환(전체 정답이면 즉시 완료), 과목당 진행 중 1개, 두 기기 동시 시작, 마지막 슬롯 제출과 새로 구성의 경합, 홈 요약의 고유 문항 수(176·194·194·199·181)를 실제 DB에서 검산합니다. **모의고사 최종 제출**은 가짜 DB(`test_progress_api.py`)로 모드 `400`·중단 `409`·멱등 재제출·합격 경계(과목 40점·평균 60점) 계산을, 실제 DB(`test_integration_db.py`)로 100문항 제출·미응답의 원장 미기록·선택 저장과 새로 구성의 잠금 경합(study_attempt 에 SHARE 잠금을 잠시 걸어 제출을 멈춰 세우는 방식)을 고정합니다.

## 2. 환경변수

`back/app/config.py` 가 저장소 루트 `.env` 를 먼저 읽고(이미 설정된 환경변수는 덮어쓰지 않음) 그다음 셸 환경변수를 봅니다. 템플릿은 `back/.env.example`.

| 이름 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `EXAM_DB_URL` | 아니오 | — | PostgreSQL 접속 문자열. `tools/load_db.py` 와 같은 값을 씁니다 |
| `DATABASE_URL` | 아니오 | — | `EXAM_DB_URL` 이 없을 때 대체 |
| `PGHOST` `PGPORT` `PGUSER` `PGPASSWORD` `PGDATABASE` | 아니오 | — | 위 둘 다 없을 때 libpq 방식으로 사용 |
| *(위가 모두 없을 때)* | — | `postgresql://yangyag@localhost:5432/app` | 내장 기본값 |
| `EXAM_API_TOKEN` | 아니오 | 없음(빈 값) | 설정하면 **쓰기(POST·PATCH) 요청에 `X-Exam-Token` 헤더 필수**. 비어 있으면 인증 없음 |
| `TEST_DB_URL` | 아니오 | — | **테스트 전용**. 통합 테스트가 붙을 DB. 있으면 `EXAM_DB_URL`/`DATABASE_URL` 보다 우선하며, 앱 자체는 이 값을 보지 않습니다(`back/tests/conftest.py` 만 읽음) |
| `EXAM_CORS_ORIGINS` | 아니오 | — | 쉼표 구분 추가 오리진. 기본 허용 오리진 `http://localhost:8091` 는 값을 넣어도 유지됩니다 |

접속을 열 때 세션 `search_path` 를 `ipe,public` 으로 고정하므로 `yangyag` 역할의 전역 설정을 바꾸지 않습니다(기존 영어 앱에 영향 없음).

`EXAM_API_TOKEN` 동작(실측):

| 요청 | `EXAM_API_TOKEN` 미설정 | 설정됨 |
|---|---|---|
| `GET` | 그대로 통과 | 그대로 통과 |
| `POST`·`PATCH` + 헤더 없음 | 통과 | `401` |
| `POST`·`PATCH` + 틀린 헤더 | 통과 | `401` |
| `POST`·`PATCH` + 맞는 헤더 | 통과 | 통과 |

## 3. 엔드포인트

26개입니다. 스키마에 나오지 않는 `/` · `/docs` · `/openapi.json` · `/figures/*` 는 위 표 참고.

- **base URL**: 개발 서버는 `http://127.0.0.1:8092` 이고, 모든 JSON 엔드포인트는 `/api` 로 시작합니다.
- **`{examId}` 형식**: `2026-1` 처럼 `연도-회차` 인 문자열입니다.
- **`{questionId}` 형식**: `2026-1-064` 처럼 `{examId}-번호(3자리 0채움)` 입니다. 1,300문항 전부 이 규칙을 지킵니다(확인함). 그래도 URL 은 `id` 를 그대로 쓰는 편이 안전합니다.
- 응답 스키마 이름은 `back/app/schemas.py`(사이클은 `back/app/cycle_schemas.py`)의 클래스명입니다.
- 아래 `curl` 예시는 **저장소 루트를 cwd** 로 가정합니다(`tmp/note.json` 같은 경로가 저장소 기준).

### 회차 · 과목 — `back/app/routers/exams.py`

| 메서드 | 경로 | 설명 | 파라미터(기본값) | 응답 |
|---|---|---|---|---|
| GET | `/api/subjects` | 과목 5개와 과목별 전체 문항 수 | — | `SubjectOut[]` |
| GET | `/api/exams` | 회차 목록(최신순) | — | `ExamOut[]` |
| GET | `/api/exams/{examId}` | 회차 상세 + 과목별 문항 수 | — | `ExamDetail` |
| GET | `/api/exams/{examId}/questions` | 회차 문항 목록(필터·페이지) | `subjectCode`(1~5), `difficulty`(1~5), `tag`(반복), `figureOnly`(false), `limit`(20, 1~200), `offset`(0) | `QuestionPage` |

### 문항 — `back/app/routers/questions.py`

| 메서드 | 경로 | 설명 | 파라미터(기본값) | 응답 |
|---|---|---|---|---|
| GET | `/api/questions/random` | 랜덤 출제(내용 기준 중복 제거) | `examId`, `subjectCode`(1~5), `tag`(반복), `figureOnly`(false), `count`(10, 1~100) | `QuestionOut[]` |
| GET | `/api/questions/{questionId}` | 문항 단건 | — | `QuestionOut` |
| POST | `/api/questions/{questionId}/answer` | 단발 채점 + 응시 기록. `sessionId` 가 종료된 세션이거나 슬롯(`study_session_item`)이 있는 세션이면 `409` | 본문 `GradeRequest` | `GradeResult` |

### 진도 — `back/app/routers/progress.py`

| 메서드 | 경로 | 설명 | 파라미터(기본값) | 응답 |
|---|---|---|---|---|
| POST | `/api/sessions` | 세션 시작 (`201`). `mode=exam_practice`·`exam` 은 회차 문항 슬롯까지 만든다 | 본문 `SessionCreate` | `SessionOut` |
| GET | `/api/sessions` | 세션 목록(최근순) | `mode`, `cycleId`, `limit`(20, 1~200), `offset`(0) | `SessionOut[]` |
| GET | `/api/sessions/{sessionId}` | 세션 단건 + 슬롯 목록 + 진행(`nextSeq`). 제출된 모의고사는 `examResult` 까지 | — | `SessionDetailOut` |
| POST | `/api/sessions/{sessionId}/finish` | 세션 종료(멱등). **슬롯이 있는 세션은 `409`** | — | `SessionOut` |
| POST | `/api/sessions/{sessionId}/submit` | **모의고사 최종 제출** — 일괄 채점 후 종료(멱등). `mode≠exam` 은 `400` | — | `ExamResultOut` |
| GET | `/api/sessions/{sessionId}/items/{seq}` | 슬롯 문항 단건. 채점 전에는 `state` 를 빼고, 채점된 슬롯은 `result` 를 준다 | — | `SessionItemDetail` |
| PUT | `/api/sessions/{sessionId}/items/{seq}/answer` | 슬롯 제출 — 연습은 즉시 채점, 모의고사는 선택만 저장 | 본문 `SlotAnswerRequest` | `SlotGradeResult` 또는 `SlotSaveOut` |
| GET | `/api/progress/questions` | 문항 상태 목록 | `bookmarked`, `wrong`, `unresolved`, `dueOn`, `limit`(50, 1~200), `offset`(0) | `ProgressItem[]` |
| GET | `/api/progress/questions/{questionId}` | 문항 상태 단건 | — | `StateOut` 또는 `null` |
| PATCH | `/api/progress/questions/{questionId}` | 북마크·메모·복습 예정일 수정 | 본문 `StateUpdate` | `StateOut` |

### 과목 사이클 — `back/app/routers/subject_cycles.py`

| 메서드 | 경로 | 설명 | 파라미터(기본값) | 응답 |
|---|---|---|---|---|
| POST | `/api/subject-cycles` | 과목 사이클 시작(목록 구성 + 라운드 1 세션) (`201`) | 본문 `CycleCreate` | `CycleOut` |
| GET | `/api/subject-cycles` | 사이클 목록(최근 생성순) | `subjectCode`(1~5), `status`(`active`\|`completed`\|`abandoned`), `limit`(20, 1~200), `offset`(0) | `CycleOut[]` |
| GET | `/api/subject-cycles/{cycleId}` | 사이클 단건 + 라운드 목록 | — | `CycleOut` |
| GET | `/api/subject-cycles/overview` | 홈 요약 — 과목 5개의 상태·고유 문항 수·진행 집계 | — | `SubjectOverviewOut[]` |

### 통계 — `back/app/routers/stats.py`

| 메서드 | 경로 | 설명 | 파라미터(기본값) | 응답 |
|---|---|---|---|---|
| GET | `/api/stats/subjects` | 과목별 정답률 | — | `SubjectStatsOut[]` |
| GET | `/api/stats/wrong-questions` | 한 번이라도 틀린 문항(최근순) | `unresolvedOnly`(false), `limit`(50, 1~200), `offset`(0) | `WrongQuestionOut[]` |
| GET | `/api/stats/review-due` | 복습 예정일이 오늘(Asia/Seoul 날짜) 이하인 문항 | `limit`(50, 1~200), `offset`(0) | `ReviewDueOut[]` |

### 태그 · 메타

| 메서드 | 경로 | 설명 | 파라미터(기본값) | 응답 |
|---|---|---|---|---|
| GET | `/api/tags` | 태그 목록(문항 많은 순) | `q`(이름 부분일치, 대소문자 무시), `limit`(100, 1~1000) | `TagOut[]` |
| GET | `/api/health` | 헬스체크. DB 연결 실패 시 `503` | — | `{status, database, dbUrlSource}` |

### 필터 의미 (혼동하기 쉬운 것들)

- `tag` 는 **반복 파라미터**이고, 여러 개를 주면 **OR** 입니다(AND 아님). `?tag=UML&tag=C언어` → UML 29개 + C언어 34개 = 63개(현재 데이터에서 겹치는 문항 없음).
- `difficulty` 는 **정확히 그 난이도**입니다(범위 아님).
- `figureOnly=true` → 도식이 있는 문항만.
- `/api/sessions` 의 `cycleId` = 그 사이클의 라운드 세션만. `mode` 와 함께 쓸 수 있습니다.
- `/api/progress/questions` 의 `wrong=true` = 한 번이라도 틀림(`wrongCount > 0`), `wrong=false` = 한 번도 틀린 적 없음(`wrongCount = 0`).
- 같은 엔드포인트의 `unresolved=true` = 마지막 응답도 틀림, `unresolved=false` = 마지막이 맞았거나 틀린 적 없음(`lastIsCorrect` 가 NULL 인 미응답 행도 여기 들어옵니다). `dueOn=2026-09-11` = 복습 예정일이 그날 이하.
- `/api/stats/wrong-questions` 의 `unresolvedOnly=true` 는 `lastIsCorrect=false` 인 것만(이쪽은 `false` 를 주는 방향이 없습니다).
- `bookmarked`·`wrong`·`unresolved` 는 값을 주지 않으면 조건이 걸리지 않습니다(전체 조회). **`false` 도 조건으로 동작합니다.**
- 이 목록은 `study_state` 행 기준입니다. 응답도 북마크·메모도 없는 문항은 행이 없어 **어느 필터로도 나오지 않습니다**.

## 4. 응답 규칙

**JSON 키는 전부 camelCase** 입니다(데이터셋 JSON 계약과 동일). 날짜·시각은 ISO 8601 문자열이고 `reviewDueOn` 은 날짜(`YYYY-MM-DD`), 나머지는 UTC 시각입니다.

### 조회 응답에는 정답이 없습니다

`QuestionOut` 계열 응답에는 `answer` · `explanation` · 보기별 `correct`/`why` 가 **들어가지 않습니다**. 채점 응답에서만 돌려줍니다. 프론트가 시험 모드에서 정답을 화면에 들고 있을 필요가 없도록 하려는 의도이고, `back/app/queries.py` 의 SELECT 에서 강제됩니다.

예외는 **채점이 끝난 슬롯** 하나입니다. `GET /api/sessions/{sessionId}/items/{seq}` 는 그 슬롯이 이미 채점된 연습(`subject`·`review`·`exam_practice`)이거나 **제출이 끝난 모의고사(`exam`)** 일 때만 채점 응답과 같은 형식의 `result`(`GradeResult`)를 함께 줍니다. 제출된 모의고사의 **미응답 문항도 `result` 가 붙습니다** — 이때 `choiceNo` 와 `result.choiceNo` 가 `null`, `isCorrect` 가 `false` 이고 정답·해설은 그대로 봅니다. 이 조회의 `state` 는 **채점 여부와 무관하게 항상 `null`** 입니다(이전 풀이의 정답 여부가 드러나지 않게 — 문항 누계는 채점 응답의 `state` 로만 봅니다). 조회는 원장을 늘리지 않고, 진행 중인 모의고사는 세션 조회에서 `isCorrect` 도 `null` 로 가립니다.

```json
{
  "id": "2026-1-001", "examId": "2026-1", "number": 1,
  "subjectCode": 1, "subjectName": "소프트웨어 설계",
  "stem": "소프트웨어 공학의 기본 원칙이라고 볼 수 없는 것은?",
  "passage": null, "passageKind": null, "difficulty": 1,
  "choices": [{"no": 1, "text": "품질 높은 소프트웨어 상품 개발"}],
  "figure": {"needed": false, "kind": null, "imageUrl": null, "alt": null},
  "tags": ["소프트웨어 공학", "기본 원칙"],
  "state": null
}
```

- `passage` + `passageKind`(`code`/`table`/`text`)는 표·코드·지문을 텍스트로 복원한 것입니다. 둘 다 null 이거나 둘 다 값이 있습니다.
- `figure.imageUrl` 은 **서버 기준 상대경로**(`/figures/2026-1/099.png`)입니다. 프론트는 API 오리진을 앞에 붙여야 합니다.
- `state` 는 그 문항의 진도 상태(`StateOut`)입니다. 응답 이력이 없으면 `null`.

### 목록 응답

`/api/exams/{examId}/questions` 만 페이지 래퍼를 씁니다. 나머지 목록은 배열을 그대로 돌려줍니다.

```json
{"items": [/* QuestionOut */], "total": 20, "limit": 20, "offset": 0}
```

`total` 은 **필터를 적용한 총 개수**입니다(회차 전체 문항 수가 아님).

### 랜덤 출제의 중복 제거 (I-01)

회차 간에 같은 문항이 여러 번 실려 있습니다(1,300문항, API 내용 키 기준 **938그룹** / `tools/dups.py` 기준 고유 847개 — `AGENTS.md` 함정 3). `/api/questions/random` 은 **한 응답 안에서 내용이 같은 문항을 한 번만** 내보냅니다. 같은 내용인지는 stem · 지문(`passage`+`passageKind`) · 보기 4개 · 도식 정보(`figure.needed`/`kind`/`alt`)를 합친 키(`content_key`)로 판정합니다.

쉼표는 **자연어 문장부호일 때만 무시**합니다. 인쇄·추출 차이로 쉼표만 다르게 실린 자연어 문항(2023-1-001·2023-1-023 의 보기, 2022-1-052·2024-3-058 등)은 계속 한 그룹입니다. 반면 코드·표의 쉼표는 문항을 가르는 정보라 보존합니다 — `passageKind` 가 `code`/`table` 인 지문은 쉼표를 하나도 지우지 않고, 그 밖의 텍스트에서도 공백 없이 영숫자에 붙은 쉼표(`print(1,23)` 의 쉼표)는 남깁니다. 그래서 같은 stem·보기라도 `print(1,23)` 과 `print(12,3)` 은 서로 다른 문항입니다(리뷰 반례, `back/app/queries.py` 의 `key_text`·`code_key_text`). 공백·줄바꿈·다른 기호도 그대로 비교하므로 stem 만 같고 지문·보기가 다른 문항은 합쳐지지 않습니다.

- 그룹마다 대표 1문항을 무작위로 고르고 그룹 순서도 무작위입니다. 여러 번 호출하면 같은 그룹에서 매번 다른 문항이 나올 수 있습니다.
- 중복을 제거한 고유 그룹이 `count` 보다 적으면 **가용한 만큼만** 돌려줍니다(오류가 아닙니다). 예: `examId=2023-1&count=100` → 99개(001·023 이 한 그룹).
- 목록(`/api/exams/{examId}/questions`) · 단건(`/api/questions/{questionId}`) 은 원본 그대로라 같은 내용의 문항이 모두 나옵니다. 회차 전체를 순서대로 푸는 화면은 이쪽을 쓰세요.
- 중복 제거는 응답을 만들 때만 하며 문항 데이터는 고치지 않습니다(원본 결함 보존). 마이그레이션·스키마 변경도 없습니다.
- 그림 파일 경로(`figure.imageUrl`)는 회차 디렉터리마다 달라서 중복 키에 넣지 않습니다. 도식의 내용(`kind`·`alt`)만 봅니다.

### 응답 스키마 필드

위에서 JSON 예시로 보여주지 않은 스키마들입니다. `*` 는 항상 있는 필드, 나머지는 `null` 이 될 수 있습니다.
`count` 계열 중 `ExamOut.questionCount`·`ExamOut.figureCount`·`TagOut.questionCount` 는 스키마 기본값이 `0` 이라 **`null` 이 되지 않습니다**(해당하는 문항이 없으면 `0`).
`QuestionOut` · `ChoiceOut` 은 "조회 응답에는 정답이 없습니다", `StateOut` 은 "채점", `GradeRequest`/`GradeResult`·`StateUpdate` 는 해당 절을, `SessionCreate`/`SessionOut`·`SlotAnswerRequest`/`SlotGradeResult`/`SlotSaveOut`·`ExamResultOut` 은 "세션과 슬롯", `CycleCreate`/`CycleOut`/`SubjectOverviewOut` 은 "과목 사이클" 절을 참고하세요.

| 스키마 | 필드 |
|---|---|
| `SubjectOut` | `code*`, `name*`, `fromNo*`, `toNo*`, `questionCount` |
| `ExamOut` | `id*`, `year*`, `round*`, `title*`, `questionCount*`, `figureCount*` |
| `ExamDetail` | `ExamOut` 전부 + `sourcePdf`, `subjects`(`SubjectOut[]`, 그 회차 기준 문항 수) |
| `TagOut` | `id*`, `name*`, `questionCount*` |
| `FigureOut` | `needed`, `kind`(`diagram`\|`screen`\|null), `imageUrl`, `alt` — 전부 선택 |
| `ProgressItem` | `StateOut` 전부 + `examId*`, `number*`, `subjectCode*`, `subjectName`, `stem*` |
| `SubjectStatsOut` | `subjectCode*`, `subjectName*`, `answered*`, `correct*`, `wrong*`, `questionsTotal*`, `questionsSeen*`, `accuracyPct` |
| `WrongQuestionOut` | `questionId*`, `examId*`, `number*`, `subjectCode*`, `subjectName*`, `stem*`, `attemptCount*`, `wrongCount*`, `lastChoiceNo`, `lastIsCorrect`, `lastAnsweredAt`, `bookmarked`, `note`, `reviewDueOn` |
| `ReviewDueOut` | `questionId*`, `examId*`, `number*`, `subjectCode*`, `subjectName*`, `stem*`, `reviewDueOn*`, `overdueDays*`, `lastIsCorrect`, `wrongCount*`, `note` |
| `SessionDetailOut` | `SessionOut` 전부 + `itemCount*`(슬롯 수), `answeredCount*`, `nextSeq`(다음 `seq`, 없으면 `null`), `items*`(`SessionItemOut[]`), `examResult`(`ExamResultOut`\|null — 제출된 모의고사만) |
| `SessionItemOut` | `seq*`, `questionId*`, `choiceNo`, `isCorrect`(진행 중 모의고사는 `null` 로 가림) |
| `SessionItemDetail` | `QuestionOut` 전부 + `seq*`, `choiceNo`, `isCorrect`, `answeredAt`, `result`(`GradeResult`\|null — 채점된 슬롯·제출된 모의고사, 미응답은 `choiceNo=null`). `state` 는 항상 `null` |
| `SlotAnswerRequest` | `choiceNo`(1~4, 선택 — 모의고사는 `null` = 선택 해제), `elapsedMs`(0~2147483647, 선택) |
| `SlotGradeResult` | `GradeResult` 전부 + `session*`(`SessionProgressOut`), `roundResult`(이 제출로 라운드가 끝났을 때만), `cycle`(사이클 라운드일 때만) |
| `SlotSaveOut` | `seq*`, `choiceNo`, `answeredAt` — 모의고사 선택 저장 응답(정답·해설 없음) |
| `GradeResult` | `questionId*`, `choiceNo`(제출된 모의고사의 미응답 문항이면 `null`), `isCorrect*`, `answer*`, `explanation*`, `keyPoint`, `choicesAnalysis*`(4개), `state*` |
| `ExamResultOut` | `sessionId*`, `itemCount*`, `answeredCount*`, `unansweredCount*`, `correctCount*`, `wrongCount*`(답했지만 틀린 수), `bySubject*`(`ExamSubjectScoreOut[]`), `averageScore*`, `passed*`, `submittedAt`(제출 시각) |
| `ExamSubjectScoreOut` | `subjectCode*`, `correct*`, `score*`(정답 수 × 5), `passed*`(40점 이상) |
| `SessionProgressOut` | `id*`, `itemCount*`, `answeredCount*`, `nextSeq`(종료된 세션이면 `null`), `finished*` |
| `RoundResultOut` | `roundNo`(회차 연습·모의고사면 `null`), `itemCount*`, `correct*`, `wrong*` |
| `CycleResultOut` | `id*`, `status*`, `nextSessionId`, `nextRoundNo`, `nextItemCount`(다음 라운드가 없으면 셋 다 `null`) |
| `CycleOut` | `id*`, `subjectCode*`, `subjectName`, `status*`(`active`\|`completed`\|`abandoned`), `startedAt*`, `endedAt`, `rounds*`(`RoundOut[]`) |
| `RoundOut` | `sessionId*`, `roundNo*`, `mode*`, `itemCount*`, `answered*`, `correct*`, `startedAt*`, `finishedAt`, `endReason` |
| `RoundSummaryOut` | `sessionId`, `roundNo`, `itemCount*`, `answered*`, `correct*` |
| `HomeCycleOut` | `id*`, `status*`, `startedAt*`, `endedAt`, `firstRound`(`RoundSummaryOut`\|null), `currentRound`(진행 중 사이클의 열린 라운드, 없으면 `null`) |
| `SubjectOverviewOut` | `subjectCode*`, `subjectName*`, `uniqueQuestionCount*`, `status*`(`not_started`\|`first_pass`\|`reviewing`\|`completed`), `cycle`(`HomeCycleOut`\|null) |

주의할 점 몇 가지:

- `SubjectStatsOut.accuracyPct` 는 **응답 기록이 없는 과목에서 `null`** 입니다(0 이 아님). `/api/stats/subjects` 는 응답이 없는 과목도 5행 전부 돌려줍니다.
- `StateOut` 자체가 `null` 일 수 있습니다 — 그 문항에 대한 행이 없을 때입니다(`study_state` 는 문항당 1행). `PATCH` 로 북마크·메모만 남긴 문항은 행이 생기므로 `state` 가 오고, 이때 `attemptCount`·`correctCount`·`wrongCount`·`streak` 는 `0`, `bookmarked` 는 보낸 값, `lastChoiceNo`·`lastIsCorrect`·`lastAnsweredAt` 은 `null` 입니다. 응답 화면에서 `state?.attemptCount ?? 0` 처럼 다루세요.
- `ReviewDueOut.overdueDays` 는 `0` 이면 오늘, 클수록 밀린 것입니다. 여기서 **‘오늘’은 Asia/Seoul 날짜**입니다 — 복습 예정일 비교와 지연 일수 계산은 한국 날짜 기준이고, 다른 시각 응답(`startedAt` 등)은 UTC 그대로입니다. DB 뷰(`ipe.v_review_due`)가 `Asia/Seoul` 기준 날짜를 씁니다.
- `WrongQuestionOut`·`ReviewDueOut` 에는 **`answer` 가 없습니다**(뷰에는 있지만 API 가 SELECT 하지 않음).

### 채점

```bash
# 1) 먼저 세션을 만들고 id 를 받습니다
curl -X POST http://127.0.0.1:8092/api/sessions \
  -H "Content-Type: application/json" -d '{"mode": "random"}'
# {"id": 16, "mode": "random", "examId": null, "subjectCode": null,
#  "startedAt": "2026-09-11T05:25:50.581831Z", "finishedAt": null,
#  "answered": 0, "correct": 0}

# 2) 그 세션으로 채점 (아래 16 은 1)에서 받은 id — 실제 값으로 바꾸세요)
curl -X POST http://127.0.0.1:8092/api/questions/2026-1-001/answer \
  -H "Content-Type: application/json" \
  -d '{"choiceNo": 1, "sessionId": 16, "elapsedMs": 1500}'

# 3) 제출(=세션 종료)하면 그 세션으로는 더 채점할 수 없습니다
curl -X POST http://127.0.0.1:8092/api/sessions/16/finish
curl -i -X POST http://127.0.0.1:8092/api/questions/2026-1-001/answer \
  -H "Content-Type: application/json" \
  -d '{"choiceNo": 1, "sessionId": 16}'
# HTTP/1.1 409 Conflict
# {"detail": "이미 종료된 세션입니다. 계속 풀려면 새 세션을 시작하세요"}
```

`GradeRequest`: `choiceNo`(필수, 1~4), `sessionId`(선택), `elapsedMs`(선택, `0` 이상 `2147483647` 이하 — 저장 컬럼 `study_attempt.elapsed_ms` 가 PostgreSQL `integer` 라 상한을 맞췄습니다. 넘으면 `422`).
`sessionId` 는 **이미 존재하는 세션 id 여야 합니다** — 없으면 `404`, **이미 종료된 세션(`finishedAt` 이 있는 세션)이면 `409`** 입니다. 세션 밖 단발 풀이로 기록하려면 필드를 생략하거나 `null` 로 보내세요(이때는 세션을 조회하지 않습니다).
**슬롯(`study_session_item`)이 있는 세션(`subject`·`review`·`exam_practice`·`exam`)이면 `409`** 입니다 — 기록은 슬롯 제출 `PUT /api/sessions/{sessionId}/items/{seq}/answer` 로만 받습니다. 문항 목록이 고정된 세션에 이 경로로 쓰면 목록·진행 위치와 어긋나기 때문입니다. `random` 세션과 `sessionId` 없는 단발 채점은 기존 그대로입니다.
이 호출은 `study_attempt` 에 1행을 넣고 `study_state` 를 갱신합니다(채점 자체가 진도 기록입니다). 그래서 `state` 가 응답에 함께 실립니다.

**제출이 그 세션의 점수를 확정합니다.** `/api/sessions/{sessionId}/finish` 로 제출한 세션에 채점을 시도하면 `409` 로 거부되고, 세션 요약(`answered`·`correct`)은 제출 시점 그대로입니다(실측 확인). 계속 풀려면 새 세션을 만들거나 `sessionId` 없이 기록하세요. 막히는 것은 **그 세션에 대한 기록**뿐이라, 문항별 누계(`study_state`)와 응시 이력(`study_attempt`)은 다른 세션의 채점으로 계속 쌓입니다.

**채점과 제출이 겹치면 먼저 도착한 쪽이 기준입니다(B-01).** 채점 트랜잭션은 세션 행을 `FOR UPDATE` 로 잠그고, 기록(`study_attempt`·`study_state`)이 커밋되는 시점에 잠금을 놓습니다(응답 직렬화는 그 뒤에 이어집니다). 그래서

- 채점이 먼저 잠금을 잡으면 `/finish` 는 그 채점이 끝날 때까지 기다렸다가 **그 채점까지 포함해** `answered`·`correct` 를 계산합니다(마지막 답안 전송과 제출이 겹쳐도 점수가 빠지지 않습니다).
- `/finish` 가 먼저 커밋되었으면 뒤에 시작한 채점이 `409` 로 거부되고 이력·상태는 늘지 않습니다.

프론트는 그래도 답안 요청 완료 후 제출하는 순서를 지키는 편이 좋습니다. 이 계약은 실 DB 통합 테스트(`test_integration_concurrency.py`)가 두 순서 모두 고정합니다.

```json
{
  "questionId": "2026-1-001", "choiceNo": 1, "isCorrect": false, "answer": 4,
  "explanation": "소프트웨어 공학은 …",
  "keyPoint": "소프트웨어 공학의 기본 원칙과 최소 인력 투입",
  "choicesAnalysis": [{"no": 1, "correct": false, "why": "품질 높은 …"}],
  "state": {"questionId": "2026-1-001", "attemptCount": 1, "correctCount": 0,
            "wrongCount": 1, "lastIsCorrect": false, "lastChoiceNo": 1,
            "lastAnsweredAt": "2026-09-11T05:25:50.920629Z", "streak": 0,
            "bookmarked": false, "note": null, "reviewDueOn": null,
            "updatedAt": "2026-09-11T05:25:50.920629Z"}
}
```

`choicesAnalysis` 는 항상 4개이고 `correct` 가 정확히 1개이며 `answer` 와 일치합니다.

### 세션과 슬롯

`SessionCreate`: `mode`(필수), `examId`, `subjectCode`(1~5), `replaceActive`(기본 `false`).

**`mode` 5종** — 정본은 `db/003_study_items.sql` 주석(`study_session_mode_chk`)이고, 표는 요약만 여기 기재합니다.

| mode | 세션 모양 | 채점 경로 |
|---|---|---|
| `subject` | 과목 사이클 라운드 1. 슬롯 = 과목 문항을 중복 제거·셔플한 목록 | `PUT /api/sessions/{id}/items/{seq}/answer` (문항별 즉시) |
| `review` | 과목 사이클 라운드 2+. 슬롯 = 직전 라운드 오답 | 위와 같음 |
| `exam_practice` | 회차별 연습. 슬롯 = 회차 문항 번호 순 | 위와 같음 |
| `exam` | 회차 모의고사. 슬롯 = 회차 문항 번호 순 | 연습과 달리 제출 전에는 선택만 저장하고, `POST /api/sessions/{id}/submit` 이 전 문항을 한 번에 채점한다 |
| `random` | 슬롯 없음 | 기존 `POST /api/questions/{questionId}/answer` |

```bash
POST /api/sessions  {"mode": "random"}                              # 201, 슬롯 없음
POST /api/sessions  {"mode": "exam_practice", "examId": "2026-1"}   # 201, 슬롯 100개
POST /api/sessions  {"mode": "exam",   "examId": "2026-1"}          # 201, 슬롯 100개
POST /api/sessions  {"mode": "subject", "subjectCode": 3}           # 400 — 사이클 API 로만
POST /api/sessions  {"mode": "review"}                              # 400 — 사이클 API 로만
```

- **`subject`·`review` 는 `400`** 입니다. 이 두 모드는 사이클 라운드 전용이라 `POST /api/subject-cycles`(라운드 1)와 채점에 따른 자동 전환(라운드 2+)으로만 만듭니다. (`mode=subject` 세션을 직접 만드는 옛 동작은 없어졌습니다.)
- `mode=exam_practice`·`exam` 에 `examId` 가 없으면 `400`, 없는 회차면 `404`, 그 회차에 문항이 없으면 `400`.
- `mode=exam_practice`·`exam` 은 **같은 모드·회차의 진행 중 세션(`finishedAt` 이 `null`)이 있으면 `409`** 입니다(DB 의 `study_session_exam_open_uk`). `replaceActive=true` 로 보내면 그 세션을 `endReason="abandoned"` 로 닫고 같은 트랜잭션에서 새로 만듭니다(부수 효과: 그 세션에 쌓인 슬롯·원장은 그대로 남지만 더 이상 기록할 수 없습니다). 두 기기에서 동시에 만들면 유니크 인덱스 위반을 `409` 로 돌려줍니다.
- `examId` 의 빈 문자열(`""` 또는 공백뿐인 값)은 **`null` 로 정규화**합니다(B-02). 프론트 선택 입력의 초기값을 그대로 보내도 되도록 한 것이고, 라우터의 존재 검사 기준(`if examId`)과도 맞습니다. 그래서 `mode=exam` + `""` 는 `400`(examId 필요)이고, `mode=random` + `""` 는 회차 없음으로 만들어집니다. `""` 가 그대로 `INSERT` 되어 `500`(외래 키 위반)이 나던 동작은 없어졌습니다.
- `random` 은 `examId`·`subjectCode` 도 받아 **세션 행에 그대로 저장합니다**(응답 `SessionOut` 에 그대로 실립니다). 랜덤 출제 자체는 `GET /api/questions/random` 이 하므로 세션의 값은 출제에 영향을 주지 않습니다(슬롯이 없음). 없는 회차·과목이면 `404`.
- 회차 연습·모의고사에 `subjectCode` 를 함께 보내도 **저장하지 않습니다**(항상 `null`) — 그 회차의 과목 구성은 문항에서 나옵니다.
- `/finish` 는 이미 끝난 세션에 다시 호출해도 현재 상태를 그대로 돌려줍니다(멱등). **슬롯이 있는 세션은 `409`** 입니다 — 연습은 마지막 슬롯을 채점하면 같은 트랜잭션에서 자동으로 끝나고, 모의고사는 최종 제출(`POST …/submit`)을 써야 합니다. 슬롯 없는 `random` 세션은 기존대로 `/finish` 로 끝냅니다.
- 종료·중단된 슬롯 세션의 **아직 안 푼 슬롯** 제출은 `409` 이고, 메시지는 모드와 `endReason` 으로 갈립니다.
  - 연습(`subject`·`review`·`exam_practice`): `abandoned` → `"중단된 세션입니다. 새로 구성한 세션에서 계속하세요"`, `finished` → `"이미 종료된 세션입니다. 계속 풀려면 새 세션을 시작하세요"`. 연습의 `finished` 분기는 정상 흐름에서 나지 않습니다(마지막 슬롯 채점이 곧 종료라 그때는 모든 슬롯이 이미 채점돼 위의 재전송 경로로 갑니다).
  - 모의고사(`exam`): `abandoned` → `"중단된 모의고사입니다. 새로 구성한 세션에서 계속하세요"`, `finished`(최종 제출 완료) → `"이미 제출된 모의고사입니다. 결과는 세션 조회로 확인하세요"`.

`SessionOut`(목록·생성 응답)에는 `cycleId`·`roundNo`·`endReason` 이 더해졌습니다. 모드별로 저장되는 대상 값은 이렇습니다(위 `SessionCreate` 규칙과 같은 내용).

| mode | `examId` | `subjectCode` | `cycleId`·`roundNo` | `endReason` |
|---|---|---|---|---|
| `subject`(라운드 1) | `null` | 사이클의 과목 | `cycleId`, `roundNo=1` | 마지막 슬롯 채점 시 `finished` · 새로 구성 시 `abandoned` |
| `review`(라운드 2+) | `null` | 사이클의 과목 | `cycleId`, `roundNo>=2` | 위와 같음 |
| `exam_practice` | 회차 | `null`(요청에 있어도 저장 안 함) | `null` | 마지막 슬롯 채점 시 `finished` · 새로 구성 시 `abandoned` (`/finish` 는 `409`) |
| `exam` | 회차 | `null`(요청에 있어도 저장 안 함) | `null` | 최종 제출(`submit`) 시 `finished` · 새로 구성 시 `abandoned` |
| `random` | 요청값(보통 `null`) | 요청값(보통 `null`) | `null` | `/finish` 로 `finished` |

`roundNo` 만 `null` 이고 `cycleId` 가 있는 조합은 CHECK(`study_session_round_chk`)가 막습니다. `GET /api/sessions?cycleId=<id>` 로 사이클의 라운드만 모아 볼 수 있습니다.

```bash
curl -X POST http://127.0.0.1:8092/api/sessions \
  -H "Content-Type: application/json" -d '{"mode": "random"}'
# {"id": 16, "mode": "random", "examId": null, "subjectCode": null,
#  "cycleId": null, "roundNo": null, "endReason": null,
#  "startedAt": "2026-09-11T05:25:50.581831Z", "finishedAt": null,
#  "answered": 0, "correct": 0}
```

#### 세션 단건·슬롯 조회

```bash
GET /api/sessions/16          # SessionDetailOut
GET /api/sessions/16/items/1  # SessionItemDetail
```

```json
{
  "id": 16, "mode": "exam_practice", "examId": "2026-1", "subjectCode": null,
  "cycleId": null, "roundNo": null, "endReason": null,
  "startedAt": "2026-09-11T05:25:50Z", "finishedAt": null, "answered": 0, "correct": 0,
  "itemCount": 100, "answeredCount": 0, "nextSeq": 1,
  "items": [{"seq": 1, "questionId": "2026-1-001", "choiceNo": null, "isCorrect": null}]
}
```

- `nextSeq` 는 **다음에 풀 슬롯의 `seq`** 입니다. 연습은 아직 채점 안 된(`isCorrect` 가 `null`) 가장 작은 `seq`, 모의고사는 선택이 없는(`choiceNo` 가 `null`) 가장 작은 `seq`, 종료된 세션이면 `null`. 이어풀기 화면은 이 번호로 `GET …/items/{seq}` 를 부르면 됩니다.
- `answeredCount` 는 연습이면 채점된 슬롯 수, 모의고사면 선택을 저장한 슬롯 수입니다(`answered`·`correct` 는 기존대로 원장(`study_attempt`) 집계라 모의고사에서는 0 으로 남습니다).
- 슬롯이 없는 `random` 세션은 `itemCount`·`answeredCount` 가 `0`, `items` 가 빈 배열입니다.
- `items[].isCorrect` 는 **진행 중인 모의고사에서 `null` 로 가려집니다**(제출 전 정답 비공개). 연습과 종료된 모의고사는 실제 값이 옵니다.
- 조회는 아무것도 기록하지 않습니다(원장이 늘지 않음). 없는 세션은 `404`, 없는 `seq` 는 `404`.
- `examResult` 는 **제출이 끝난 모의고사에만** 실리고(진행 중이면 `null`), 모의고사 최종 제출 응답과 같은 점수 요약입니다 — "모의고사 최종 제출" 절 참고.
- `SessionItemDetail` 은 `QuestionOut` 전부 + `seq`·`choiceNo`·`isCorrect`·`answeredAt`·`result` 입니다. `result`·`state` 와 제출된 모의고사의 미응답 문항 규칙은 위 **"조회 응답에는 정답이 없습니다"** 절을 참고하세요.

#### 슬롯 제출 — `PUT /api/sessions/{sessionId}/items/{seq}/answer`

`SlotAnswerRequest`: `choiceNo`(1~4, 선택), `elapsedMs`(선택).

**연습(`subject`·`review`·`exam_practice`)** — 제출하면 즉시 채점·기록하고 `SlotGradeResult` 를 돌려줍니다.

```bash
curl -X PUT http://127.0.0.1:8092/api/sessions/16/items/1/answer \
  -H "Content-Type: application/json" -d '{"choiceNo": 3, "elapsedMs": 4200}'
```

```json
{
  "questionId": "2026-1-001", "choiceNo": 3, "isCorrect": false, "answer": 4,
  "explanation": "…", "keyPoint": "…", "choicesAnalysis": [{"no": 3, "correct": false, "why": "…"}],
  "state": {"questionId": "2026-1-001", "attemptCount": 1, "…": "…"},
  "session": {"id": 16, "itemCount": 100, "answeredCount": 1, "nextSeq": 2, "finished": false},
  "roundResult": null,
  "cycle": null
}
```

- `roundResult` 는 **이 제출로 라운드(세션)가 끝났을 때만** 붙습니다: `{"roundNo": 2, "itemCount": 26, "correct": 20, "wrong": 6}`. 회차 연습·모의고사는 `roundNo` 가 `null` 입니다.
- `cycle` 은 사이클 라운드일 때만 붙습니다: `{"id": 7, "status": "active", "nextSessionId": 13, "nextRoundNo": 3, "nextItemCount": 6}`. 다음 라운드가 없으면(사이클이 완료됐으면) `next*` 셋이 `null` 이고 `status` 가 `completed` 입니다.
- **마지막 슬롯을 채점하면 같은 트랜잭션에서 라운드가 끝납니다** — 오답이 있으면 다음 라운드(`review`, 직전 오답 셔플)가 만들어지고, 없으면 사이클이 `completed` 로 바뀝니다. 응답의 `cycle.nextSessionId` 가 곧바로 다음 라운드 세션 id 입니다.
- **재전송 멱등**: 같은 보기로 이미 채점된 슬롯에 다시 보내면 기록을 늘리지 않고 저장된 결과와 현재 진행 상태를 그대로(`200`) 돌려줍니다. **다른 보기면 `409`** (`"이미 채점된 문항입니다. 같은 보기만 다시 보낼 수 있습니다"`). 연습 슬롯에 `choiceNo` 를 빼고 보내면 `400`.
- 잠금 순서는 세션 → 슬롯 → 사이클이라, 두 기기에서 같은 슬롯을 동시에 제출해도 뒤 요청이 앞 결과를 보고 같은 보기(`200`)/다른 보기(`409`)를 판정합니다.
- 종료·중단된 세션의 **아직 안 푼 슬롯** 제출은 `409` 입니다. 이미 채점된 슬롯에 같은 보기를 다시 보내는 재전송은 세션이 끝났어도 `200` 입니다(결과가 바뀌지 않으므로).

**모의고사(`exam`)** — 선택만 저장하고 정답·해설을 주지 않습니다(정답 비공개).

```bash
curl -X PUT http://127.0.0.1:8092/api/sessions/16/items/1/answer \
  -H "Content-Type: application/json" -d '{"choiceNo": 2}'      # 200 {"seq":1,"choiceNo":2,"answeredAt":"…"}
curl -X PUT http://127.0.0.1:8092/api/sessions/16/items/1/answer \
  -H "Content-Type: application/json" -d '{"choiceNo": null}'   # 선택 해제 → answeredAt 도 null
```

- 여러 번 보내도 저장만 덮어씁니다(제출 전 자유 수정). `choiceNo: null` 은 선택 해제.
- `elapsedMs` 는 이 경로에서 저장하지 않습니다 — 모의고사 원장 행의 `elapsedMs` 는 제출 때 `null` 로 들어갑니다.
- 제출(`finishedAt` 이 있는 세션) 뒤에는 `409` 입니다 — 최종 제출이면 `"이미 제출된 모의고사입니다. 결과는 세션 조회로 확인하세요"`, `replaceActive` 로 중단된 세션이면 `"중단된 모의고사입니다…"`.

#### 모의고사 최종 제출 — `POST /api/sessions/{sessionId}/submit`

한 트랜잭션에서 전 문항을 채점하고 세션을 끝냅니다(`back/app/routers/progress.py` 의 `submit_session`). **`mode=exam` 전용**이고 쓰기 요청이므로 `EXAM_API_TOKEN` 설정 시 `X-Exam-Token` 헤더가 필요합니다.

```bash
curl -X POST http://127.0.0.1:8092/api/sessions/16/submit
```

```json
{
  "sessionId": 16, "itemCount": 100, "answeredCount": 95, "unansweredCount": 5,
  "correctCount": 70, "wrongCount": 25,
  "bySubject": [
    {"subjectCode": 1, "correct": 14, "score": 70, "passed": true},
    {"subjectCode": 2, "correct": 11, "score": 55, "passed": true},
    {"subjectCode": 3, "correct": 17, "score": 85, "passed": true},
    {"subjectCode": 4, "correct": 12, "score": 60, "passed": true},
    {"subjectCode": 5, "correct": 16, "score": 80, "passed": true}
  ],
  "averageScore": 70.0, "passed": true,
  "submittedAt": "2026-09-11T05:25:50.581831Z"
}
```

- **점수 기준은 정보처리기사 필기입니다** — 과목당 20문항·문항당 5점. `score` = 그 과목 정답 수 × 5(과목 만점 100점), `averageScore` = 세션에 있는 과목 점수의 평균(소수 첫째 자리, 과목이 하나도 없으면 `0.0`), `passed` = **매 과목 40점 이상이면서 전 과목 평균 60점 이상**일 때만 `true`.
- **미응답은 점수상 오답**(0점)입니다. 다만 원장(`study_attempt`)·누계(`study_state`)에는 **한 행도 남기지 않습니다** — `study_attempt.choice_no` 는 `NOT NULL` 이고, 나중에 답을 채워 점수를 바꾸는 일도 없게 하려는 것입니다. 슬롯은 `isCorrect=false`·`choiceNo=null` 로 남아 결과 화면이 "미응답"으로 구분할 수 있습니다.
- 집계: `answeredCount` = 선택을 저장한 슬롯 수, `unansweredCount` = 나머지, `correctCount` = 맞힌 수, `wrongCount` = **답했지만 틀린 수**(미응답 제외). 그래서 `itemCount = answeredCount + unansweredCount = correctCount + wrongCount + unansweredCount` 입니다.
- **재제출은 멱등**입니다 — 이미 제출된 세션에 다시 보내면 아무것도 쓰지 않고 같은 본문(`200`)을 돌려줍니다. 네트워크 오류 뒤 그대로 다시 보내면 됩니다.
- **결과 재조회**: `GET /api/sessions/{id}` 의 `examResult` 가 같은 점수 요약을 주고(진행 중이면 `null`), 문항별 정답·해설은 `GET /api/sessions/{id}/items/{seq}` 의 `result` 로 봅니다 — 미응답 문항도 `choiceNo=null`·`isCorrect=false` 로 `result` 가 붙습니다. **조회는 원장을 늘리지 않습니다.**
- 상태 코드: `400` — `mode` 가 `exam` 이 아님(연습은 마지막 문항에서 자동 종료되고 `random` 은 `/finish`), `404` — 없는 세션, `409` — `replaceActive` 로 중단된 모의고사(제출된 적이 없어 결과도 없음).
- **잠금 순서**(`back/app/routers/progress.py` 의 `submit_session` docstring): 세션 행을 `FOR UPDATE` 로 잡은 뒤 슬롯을 잠급니다. 제출과 선택 저장이 겹치면 세션 잠금이 순서를 정해 **제출 뒤에 도착한 저장은 `409`** 입니다. 제출이 끝난 세션은 '진행 중'이 아니라서 `replaceActive=true` 로 새로 구성해도 중단되지 않습니다(제출 결과 보존). 두 경합 모두 실 DB 통합 테스트(`test_integration_db.py`)가 고정합니다.
- 세션 요약(`SessionOut.answered`·`correct`)은 기존대로 원장 집계입니다 — 제출 뒤에는 `answered` 가 답한 문항 수가 됩니다. 점수·미응답 수는 `examResult` 쪽을 보세요.

### 과목 사이클과 홈 요약 — `back/app/routers/subject_cycles.py`

`POST /api/subject-cycles` 는 과목 문항 전체로 목록을 구성하고 라운드 1 세션까지 만듭니다(`back/app/routers/subject_cycles.py` 의 `create_subject_cycle`).

```bash
curl -X POST http://127.0.0.1:8092/api/subject-cycles \
  -H "Content-Type: application/json" -d '{"subjectCode": 1, "replaceActive": false}'
# 201
```

```json
{
  "id": 7, "subjectCode": 1, "subjectName": "소프트웨어 설계", "status": "active",
  "startedAt": "2026-09-11T05:25:50Z", "endedAt": null,
  "rounds": [{"sessionId": 12, "roundNo": 1, "mode": "subject", "itemCount": 176,
              "answered": 0, "correct": 0, "startedAt": "2026-09-11T05:25:50Z",
              "finishedAt": null, "endReason": null}]
}
```

- **목록 구성**: 과목 문항 260개를 `content_key` 로 묶어 그룹 대표(가장 최근 회차 = id 최대)를 고르고 무작위로 섞어 슬롯 `seq` 1..N 으로 저장합니다(과목별 176·194·194·199·181개). 목록은 만든 뒤 바뀌지 않습니다.
- **진행 중(`active`) 사이클이 이미 있으면 `409`** 입니다(DB 의 `study_cycle_active_uk`). `replaceActive=true` 면 그 시점에 보이는 열린 라운드 세션과 사이클을 같은 트랜잭션에서 `abandoned` 로 닫고 새 사이클을 만듭니다. 두 기기에서 동시에 시작해도 유니크 인덱스 위반을 `409` 로 돌려줍니다.
- 없는 과목이면 `404`, 그 과목에 문항이 없으면 `400`(현재 데이터에는 없음).
- 201 응답의 `rounds[0].sessionId` 가 라운드 1 세션입니다. 이후 풀이는 세션·슬롯 API 로 합니다(위 "세션과 슬롯").

`GET /api/subject-cycles/{cycleId}` 는 사이클 상태 + 라운드 목록(위와 같은 모양)이고, 없는 사이클은 `404` 입니다. 라운드 집계는 **슬롯 기준**이라 진행 중에도 바로 갱신됩니다(`itemCount`·`answered`·`correct`).
`GET /api/subject-cycles?subjectCode=1&status=active&limit=20&offset=0` 은 사이클 목록(최근 생성순)입니다.
`GET /api/subject-cycles/overview` 는 홈 요약입니다(읽기 전용, 과목 5행 고정).

```json
[{
  "subjectCode": 1, "subjectName": "소프트웨어 설계", "uniqueQuestionCount": 176,
  "status": "reviewing",
  "cycle": {"id": 7, "status": "active", "startedAt": "2026-09-11T05:25:50Z", "endedAt": null,
            "firstRound":   {"sessionId": 12, "roundNo": 1, "itemCount": 176, "answered": 176, "correct": 150},
            "currentRound": {"sessionId": 13, "roundNo": 2, "itemCount": 26, "answered": 5, "correct": 3}}
}]
```

| `status` | 조건 | 홈 동작(`subject_cycle_overview`) |
|---|---|---|
| `not_started` | 진행 중·완료 사이클이 없음(중단(`abandoned`)만 있는 과목도 여기) | 시작하기 |
| `first_pass` | 진행 중 사이클의 열린 라운드가 1 | 이어서 풀기·새로 구성하기 |
| `reviewing` | 진행 중 사이클의 열린 라운드가 2 이상 | 이어서 풀기·새로 구성하기 |
| `completed` | 진행 중 사이클은 없고 완료한 사이클이 있음 | 새로 구성하기 |

- `cycle` 은 **진행 중 사이클, 없으면 마지막 완료 사이클**입니다(완료 사이클이면 `currentRound` 가 `null`). `not_started` 면 `cycle` 자체가 `null` 입니다.
- `uniqueQuestionCount` 는 요청할 때마다 계산하는 중복 제거 문항 수(176·194·194·199·181)입니다.
- `currentRound` 는 진행 중 사이클의 **열린 라운드**입니다. 경합 뒤 열린 라운드가 없으면(아래 경고) `null` 이고, 상태는 그 사이클의 마지막 라운드 번호로 판정합니다.

> **⚠ 홈·사이클 조회는 `status='active'` 사이클만 근거로 삼습니다.** `replaceActive=true` 가 열린 라운드를 잠그고 사이클을 중단시키는 사이, 다른 요청이 마지막 슬롯을 채점해 새 라운드를 커밋하면 그 라운드는 중단된 사이클에 `finishedAt` 없이 남을 수 있습니다(`back/app/cycles.py` 의 `replace_active_cycle` docstring — 잠금 순서를 뒤집으면 ABBA 데드락). 'abandoned 사이클 = 열린 세션 없음' 을 가정하면 안 되고, 남은 라운드의 마지막 슬롯을 채점하면 라운드만 닫히며 자동으로 회복합니다. 같은 경고가 `db/README.md` 경고 2에 있습니다.

### 진도 상태 수정

```bash
curl -X PATCH http://127.0.0.1:8092/api/progress/questions/2026-1-001 \
  -H "Content-Type: application/json" \
  --data-binary @tmp/note.json     # {"bookmarked": true, "note": "헷갈림", "reviewDueOn": "2026-09-20"}
```

`bookmarked` · `note` · `reviewDueOn` 중 **하나 이상**을 보내야 합니다. 셋 다 없으면 `400`.
보낸 필드만 바뀌고 나머지는 유지됩니다. 응답 이력이 없던 문항은 행이 새로 생깁니다.

> **Git Bash 주의** — 본문에 한글이 있으면 `-d '{"note":"헷갈림"}'` 처럼 인라인으로 넘기지 마세요.
> Git Bash 가 네이티브 `curl.exe` 로 인자를 넘길 때 코드페이지(cp949)로 변환해 UTF-8 이 깨지고,
> `400 {"detail":"There was an error parsing the body"}` 가 돌아옵니다.
> 위처럼 **파일에 쓰고 `--data-binary @파일`** 로 넘기면 됩니다(`tmp/` 는 gitignore).
> 프론트에서 HTTP 클라이언트로 보낼 때는 해당 없습니다.

### 오류 규약

| 상태 | 언제 |
|---|---|
| `400` | 규칙 위반 — 필드 없는 `PATCH`, `mode=exam_practice`·`exam` 인데 `examId` 없음, `subject`·`review` 세션 생성 시도, 연습 슬롯에 `choiceNo` 없음, `mode=exam` 이 아닌 세션에 `POST /api/sessions/{id}/submit` |
| `401` | `EXAM_API_TOKEN` 설정 시 쓰기 요청에 토큰이 없거나 틀림 |
| `404` | 없는 회차·문항·과목·세션·사이클·슬롯(`seq`) |
| `409` | 진행 중 세션·사이클과 충돌하거나 이미 끝난 세션에 쓰기 — ① `subject`·`review`·`exam_practice`·`exam` 세션으로 `POST /api/questions/{id}/answer`, ② 슬롯 세션에 `POST /api/sessions/{id}/finish`, ③ `exam_practice`·`exam` 생성 시 같은 모드·회차의 진행 중 세션(→ `replaceActive=true`), ④ `POST /api/subject-cycles` 시 진행 중 사이클(→ `replaceActive=true`), ⑤ 채점된 연습 슬롯에 다른 보기 재전송, ⑥ 종료·중단된 세션의 슬롯 제출, ⑦ 중단(`abandoned`)된 모의고사에 `submit` |
| `422` | 스키마 위반 — `choiceNo` 가 1~4 밖, `elapsedMs` 가 0~2147483647 밖, `limit` 이 범위 밖 등 |
| `500` | 그 밖의 서버 오류 |
| `503` | DB 에 연결할 수 없거나 커넥션 풀이 아직 초기화되지 않음(DB 를 쓰는 엔드포인트) |

오류 본문은 FastAPI 표준대로 `{"detail": "..."}` 이고 메시지는 한글입니다. DB 장애일 때는 `{"detail": "DB 에 연결할 수 없습니다"}` 입니다.

### DB 가 내려가 있을 때 (실측)

DB 를 쓰는 엔드포인트가 **2초 안에 `503`** 을 돌려줍니다(루트 `/` · `/docs` · `/figures` 는 DB 를 쓰지 않아 정상 응답). 커넥션 풀 대기 시간이 `POOL_TIMEOUT`(2초, `back/app/db.py`)이라 요청이 오래 묶이지 않습니다.

| 요청 | 수정 전 | 지금 |
|---|---|---|
| `GET /api/health` | `503` 2.10초 | `503` 2.09초 |
| `GET /api/exams` | `500` 30.03초 | `503` 2.04초 |
| `GET /api/stats/subjects` | `500` 30.04초 | `503` 2.02초 |
| `POST /api/sessions`(쓰기) | `500` 30.02초 | `503` 2.02초 |

수정 전에는 데이터 엔드포인트가 풀 기본 타임아웃(30초)을 기다린 뒤 처리되지 않은 `psycopg_pool.PoolTimeout` 으로 `500 Internal Server Error` 가 되어, 프론트에서 DB 장애가 서버 버그처럼 보였습니다. 지금은 헬스체크와 같은 `503` 이고 본문도 `{"detail": "DB 에 연결할 수 없습니다"}` 로 옵니다. 조회·쓰기 엔드포인트 10개(`/api/exams`·`/api/subjects`·`/api/tags`·`/api/stats/*`·`/api/progress/*`·`/api/sessions`·`/api/questions/*/answer` 등)를 모두 호출해 `503` 과 2.00~2.09초를 확인했습니다(**수동 실측**). 자동 테스트(`back/tests/test_db_unavailable.py`)는 `/api/exams`·`/api/sessions`·`/api/health` 3개 경로만 고정합니다.

`/api/health` 는 `ping()` 이 예외를 삼키므로 DB 가 죽어 있어도 `503` + `{"status":"degraded","database":"unavailable"}` 을 돌려줍니다(동작은 수정 전과 같습니다). 커넥션 풀이 아직 만들어지지 않은 시점(앱 기동 전)도 같은 `503` 입니다.

## 5. 의존 DB 객체

전부 `ipe` 스키마입니다(로컬 `app` DB · 운영 EC2 `exam` DB). DDL 은 `db/001_schema.sql`(문항)·`db/002_progress.sql`(진도)·`db/003_study_items.sql`(세션 슬롯·과목 사이클)·`db/004_session_comments.sql`(study_session 코멘트 정정), 컬럼 의미는 `db/README.md`.

| 객체 | 종류 | 쓰는 곳 |
|---|---|---|
| `ipe.exam` | 테이블 | 회차 목록·상세, 세션 대상 검증 |
| `ipe.subject` | 테이블 | 과목 목록, 문항 조회 조인 |
| `ipe.question` | 테이블 | 문항 조회·채점, `answer`/`explanation` 은 채점 응답에만 |
| `ipe.question_choice` | 테이블 | 보기 4개, 보기별 해설(채점 응답) |
| `ipe.tag` · `ipe.question_tag` | 테이블 | 태그 목록, 태그 필터 |
| `ipe.study_session` | 테이블 | 세션 시작·종료, 사이클 라운드(`cycle_id`·`round_no`)·종료 사유(`end_reason`) |
| `ipe.study_cycle` | 테이블 | 과목 사이클 시작·중단·완료, 홈 요약 |
| `ipe.study_session_item` | 테이블 | 세션의 고정 문항 목록·답안 슬롯(진행 위치·라운드 집계) |
| `ipe.study_attempt` | 테이블 | 채점할 때마다 1행 append, 통계 원장 |
| `ipe.study_state` | 테이블 | 문항별 현재 상태(북마크·메모·복습 예정일·연속 정답) |
| `ipe.v_subject_stats` | 뷰 | `/api/stats/subjects` |
| `ipe.v_wrong_questions` | 뷰 | `/api/stats/wrong-questions` |
| `ipe.v_review_due` | 뷰 | `/api/stats/review-due` |

API 는 `v_wrong_questions` · `v_review_due` 에 들어 있는 `answer` 컬럼을 **SELECT 하지 않습니다**. 뷰를 직접 조회할 때와 응답이 다르니 주의하세요.

유니크 인덱스 4종(`study_cycle_active_uk`·`study_session_cycle_round_uk`·`study_session_cycle_open_uk`·`study_session_exam_open_uk`)이 API 의 `409`·라운드 전환을 떠받칩니다. 특히 **`study_session_exam_open_uk` 는 값이 있는 DB에 같은 `(mode, exam_id)` 의 열린 세션이 2개 이상이면 생성에 실패**하고, `load_db.py --init` 이 한 트랜잭션이라 전체가 롤백됩니다 — 기존 DB에 마이그레이션을 적용할 때의 주의사항은 `db/README.md` 경고 1.

데이터 규모: 문항 1,300 / 보기 5,200 / 회차 13. 회차 간 중복 문항이 있어 **API 내용 키 기준 938그룹**(과목별 고유 문항 176·194·194·199·181)이고, 더 느슨한 정규화를 쓰는 `tools/dups.py` 기준으로는 고유 847개입니다(`AGENTS.md` 함정 3). **`/api/questions/random` 과 과목 사이클 구성은 내용이 같은 문항을 한 그룹으로 묶어** 그룹마다 1문항만 씁니다(위 ‘랜덤 출제의 중복 제거’ 절). 랜덤의 중복 제거는 **한 응답 안에서만** 보장합니다 — 호출이 끝나면 다시 뽑으므로 다음 호출에서 같은 그룹의 다른 문항이 나올 수 있습니다(그룹 대표가 무작위). 고유 그룹이 `count` 보다 적으면 가용분만 나옵니다. 목록·단건 조회는 원본 그대로라 중복 문항이 모두 보입니다.

## 6. 프론트에서 붙일 때

- 개발 프론트 오리진은 `http://localhost:8091` 이 기본 허용입니다. 다른 포트·도메인이면 `EXAM_CORS_ORIGINS` 에 쉼표로 추가하세요.
- 쓰기 요청(`POST /api/sessions`, `/finish`, `/submit`, `/answer`, `POST /api/subject-cycles`, `PUT …/items/{seq}/answer`)과 `PATCH` 는 `EXAM_API_TOKEN` 을 설정한 경우에만 `X-Exam-Token` 헤더가 필요합니다.
- 그림은 `/figures/...` 경로로 옵니다. DB 에는 경로·`alt` 만 있고 바이너리는 없으니 API 오리진 기준으로 해석하세요.
- 타입이 필요하면 `http://127.0.0.1:8092/openapi.json` 에서 생성하세요.
- DB 장애는 DB 를 쓰는 엔드포인트가 2초 내 `503`(`{"detail":"DB 에 연결할 수 없습니다"}`)으로 알려줍니다. 상태·사유까지 보려면 `/api/health`(2초 내 `503`, `database: "unavailable"`)를 쓰세요.

## 7. 알아둘 것

- **배포는 docker 이미지 2종(`exam-back`·`exam-front`) + compose(`deploy/`)로 합니다** — 절차는 `deploy/README.md`. 이 문서는 로컬 실행만 다룹니다. DB 접속·토큰(`EXAM_API_TOKEN`)·CORS 는 환경변수로 받고, 그림 디렉터리는 **고정 경로**(`FIGURES_DIR` = `data/figures`, `back/app/main.py` 가 `/figures` 로 마운트)입니다.
- 쿼리 로그·요청 추적은 넣지 않았습니다. `uvicorn` 로그 + 앱 경고 1줄(DB 실패·그림 디렉터리)뿐입니다.
- 인증은 단일 사용자 전제의 공유 토큰 하나뿐입니다. 사용자별 계정·권한은 없습니다.
- `POST /api/questions/{id}/answer` 는 **채점과 진도 기록을 분리할 수 없습니다.** 정답만 확인하고 기록을 남기고 싶지 않은 경우는 지금 지원하지 않습니다(슬롯 세션에는 이 경로를 쓸 수 없습니다 — 슬롯 제출이 기록 경로입니다).
- **모의고사 최종 제출은 `POST /api/sessions/{id}/submit` 입니다**(`back/app/routers/progress.py` 의 `submit_session`, 위 "모의고사 최종 제출" 절). 미응답은 점수상 오답이지만 원장·누계에 남기지 않고, 재제출은 멱등입니다.
- 과목 사이클의 라운드 전환·중단은 `advance_round_if_complete`·`replace_active_cycle`(`back/app/cycles.py`)이 맡고, 조회·집계는 `back/app/cycle_queries.py` 가 **`status='active'` 사이클만 근거로** 합니다.
