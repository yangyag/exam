# back/ — 정보처리기사 필기 API (FastAPI)

`app` DB 의 `ipe` 스키마를 읽어 **문항 조회 · 채점 · 진도** 를 제공하는 HTTP API 입니다.
프론트(Nuxt)가 이 문서만 보고 붙일 수 있는 수준을 목표로 하고, 더 자세한 내용은 코드와 `/openapi.json` 을 정본으로 봅니다.

전제: `app` DB 의 `ipe` 스키마에 문항이 적재돼 있어야 합니다(`db/README.md`). 접속 정보가 없거나 DB 가 내려가 있으면 모든 엔드포인트가 2초 안에 `503` 을 돌려줍니다(`/api/health` 는 `{"status":"degraded","database":"unavailable"}`).

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

Linux·EC2 는 인터프리터 경로만 `.venv/bin/python` 으로, PowerShell 은 2) 를 `$env:EXAM_DB_URL='...'` 로 바꾸면 됩니다.

기동 확인:

```bash
curl http://127.0.0.1:8092/api/health
# {"status":"ok","database":"ok","dbUrlSource":"EXAM_DB_URL"}
```

**저장소 루트에 `.env` 가 없는 곳에서는 2) 를 반드시 하세요** — 새로 clone 한 저장소나 `git worktree` 에는 `.env` 가 따라오지 않습니다(gitignore). 없으면 앱이 조용히 내장 기본값 `postgresql://yangyag@localhost:5432/app`(비밀번호 없음)을 쓰고, `/api/health` 가 이렇게 나옵니다:

```
{"status":"degraded","database":"unavailable","dbUrlSource":"기본값"}
```

`dbUrlSource` 가 어느 출처를 썼는지 알려줍니다. `기본값` 이면 2) 를 빠뜨린 것입니다.

| 주소 | 설명 |
|---|---|
| `http://127.0.0.1:8092/docs` | Swagger UI (엔드포인트를 브라우저에서 직접 호출 가능) |
| `http://127.0.0.1:8092/openapi.json` | OpenAPI 스키마 (프론트 타입 생성용) |
| `http://127.0.0.1:8092/api/health` | 헬스체크 |
| `http://127.0.0.1:8092/figures/<회차>/<번호>.png` | 문항 도식 이미지 정적 서빙 |

`--reload` 는 개발용입니다. **배포 방식(docker · systemd 등)은 아직 미정**이라 이 문서에서는 다루지 않습니다.

### 테스트

```bash
cd back
.venv/Scripts/python -m pytest                       # 전체 79개 (DB 접속 정보가 없으면 통합 4개는 skip)
.venv/Scripts/python -m pytest -m "not integration"  # DB 없이 75개
.venv/Scripts/python -m pytest -m integration        # 실제 ipe DB 가 있어야 도는 4개
```

`pytest`·`httpx` 는 `requirements.txt` 에 들어 있어 1) 의 설치만으로 돌아갑니다. 진도 행을 만드는 통합 테스트는 끝나면 스스로 되돌리고, DB 없이 503 을 확인하는 `test_db_unavailable.py` 는 접속할 수 없는 주소(127.0.0.1:1)만 씁니다.

## 2. 환경변수

`back/app/config.py` 가 저장소 루트 `.env` 를 먼저 읽고(이미 설정된 환경변수는 덮어쓰지 않음) 그다음 셸 환경변수를 봅니다. 템플릿은 `back/.env.example`.

| 이름 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `EXAM_DB_URL` | 아니오 | — | PostgreSQL 접속 문자열. `tools/load_db.py` 와 같은 값을 씁니다 |
| `DATABASE_URL` | 아니오 | — | `EXAM_DB_URL` 이 없을 때 대체 |
| `PGHOST` `PGPORT` `PGUSER` `PGPASSWORD` `PGDATABASE` | 아니오 | — | 위 둘 다 없을 때 libpq 방식으로 사용 |
| *(위가 모두 없을 때)* | — | `postgresql://yangyag@localhost:5432/app` | 내장 기본값 |
| `EXAM_API_TOKEN` | 아니오 | 없음(빈 값) | 설정하면 **쓰기(POST·PATCH) 요청에 `X-Exam-Token` 헤더 필수**. 비어 있으면 인증 없음 |
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

18개입니다. 스키마에 나오지 않는 `/` · `/docs` · `/openapi.json` · `/figures/*` 는 위 표 참고.

- **base URL**: 개발 서버는 `http://127.0.0.1:8092` 이고, 모든 JSON 엔드포인트는 `/api` 로 시작합니다.
- **`{examId}` 형식**: `2026-1` 처럼 `연도-회차` 인 문자열입니다.
- **`{questionId}` 형식**: `2026-1-064` 처럼 `{examId}-번호(3자리 0채움)` 입니다. 1,300문항 전부 이 규칙을 지킵니다(확인함). 그래도 URL 은 `id` 를 그대로 쓰는 편이 안전합니다.
- 응답 스키마 이름은 `back/app/schemas.py` 의 클래스명입니다.
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
| GET | `/api/questions/random` | 랜덤 출제 | `examId`, `subjectCode`(1~5), `tag`(반복), `figureOnly`(false), `count`(10, 1~100) | `QuestionOut[]` |
| GET | `/api/questions/{questionId}` | 문항 단건 | — | `QuestionOut` |
| POST | `/api/questions/{questionId}/answer` | 채점 + 응시 기록 | 본문 `GradeRequest` | `GradeResult` |

### 진도 — `back/app/routers/progress.py`

| 메서드 | 경로 | 설명 | 파라미터(기본값) | 응답 |
|---|---|---|---|---|
| POST | `/api/sessions` | 세션 시작 (`201`) | 본문 `SessionCreate` | `SessionOut` |
| GET | `/api/sessions` | 세션 목록(최근순) | `mode`, `limit`(20, 1~200), `offset`(0) | `SessionOut[]` |
| POST | `/api/sessions/{sessionId}/finish` | 세션 종료(멱등) | — | `SessionOut` |
| GET | `/api/progress/questions` | 문항 상태 목록 | `bookmarked`, `wrong`, `unresolved`, `dueOn`, `limit`(50, 1~200), `offset`(0) | `ProgressItem[]` |
| GET | `/api/progress/questions/{questionId}` | 문항 상태 단건 | — | `StateOut` 또는 `null` |
| PATCH | `/api/progress/questions/{questionId}` | 북마크·메모·복습 예정일 수정 | 본문 `StateUpdate` | `StateOut` |

### 통계 — `back/app/routers/stats.py`

| 메서드 | 경로 | 설명 | 파라미터(기본값) | 응답 |
|---|---|---|---|---|
| GET | `/api/stats/subjects` | 과목별 정답률 | — | `SubjectStatsOut[]` |
| GET | `/api/stats/wrong-questions` | 한 번이라도 틀린 문항(최근순) | `unresolvedOnly`(false), `limit`(50, 1~200), `offset`(0) | `WrongQuestionOut[]` |
| GET | `/api/stats/review-due` | 복습 예정일이 오늘 이하인 문항 | `limit`(50, 1~200), `offset`(0) | `ReviewDueOut[]` |

### 태그 · 메타

| 메서드 | 경로 | 설명 | 파라미터(기본값) | 응답 |
|---|---|---|---|---|
| GET | `/api/tags` | 태그 목록(문항 많은 순) | `q`(이름 부분일치, 대소문자 무시), `limit`(100, 1~1000) | `TagOut[]` |
| GET | `/api/health` | 헬스체크. DB 연결 실패 시 `503` | — | `{status, database, dbUrlSource}` |

### 필터 의미 (혼동하기 쉬운 것들)

- `tag` 는 **반복 파라미터**이고, 여러 개를 주면 **OR** 입니다(AND 아님). `?tag=UML&tag=C언어` → UML 29개 + C언어 34개 = 63개(현재 데이터에서 겹치는 문항 없음).
- `difficulty` 는 **정확히 그 난이도**입니다(범위 아님).
- `figureOnly=true` → 도식이 있는 문항만.
- `/api/progress/questions` 의 `wrong` = 한 번이라도 틀림(`wrongCount > 0`), `unresolved` = 마지막 응답도 틀림, `dueOn=2026-09-11` = 복습 예정일이 그날 이하.
- `/api/stats/wrong-questions` 의 `unresolvedOnly=true` 는 `lastIsCorrect=false` 인 것만.
- `bookmarked`·`wrong`·`unresolved` 는 값을 주지 않으면 조건이 걸리지 않습니다(전체 조회).

## 4. 응답 규칙

**JSON 키는 전부 camelCase** 입니다(데이터셋 JSON 계약과 동일). 날짜·시각은 ISO 8601 문자열이고 `reviewDueOn` 은 날짜(`YYYY-MM-DD`), 나머지는 UTC 시각입니다.

### 조회 응답에는 정답이 없습니다

`QuestionOut` 계열 응답에는 `answer` · `explanation` · 보기별 `correct`/`why` 가 **들어가지 않습니다**. 채점 응답에서만 돌려줍니다. 프론트가 시험 모드에서 정답을 화면에 들고 있을 필요가 없도록 하려는 의도이고, `back/app/queries.py` 의 SELECT 에서 강제됩니다.

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

### 응답 스키마 필드

위에서 JSON 예시로 보여주지 않은 스키마들입니다. `*` 는 항상 있는 필드, 나머지는 `null` 이 될 수 있습니다.
`QuestionOut` · `ChoiceOut` 은 "조회 응답에는 정답이 없습니다", `StateOut` 은 "채점", `GradeRequest`/`GradeResult`·`SessionCreate`/`SessionOut`·`StateUpdate` 는 각각 해당 절 참고.

| 스키마 | 필드 |
|---|---|
| `SubjectOut` | `code*`, `name*`, `fromNo*`, `toNo*`, `questionCount` |
| `ExamOut` | `id*`, `year*`, `round*`, `title*`, `questionCount`, `figureCount` |
| `ExamDetail` | `ExamOut` 전부 + `sourcePdf`, `subjects`(`SubjectOut[]`, 그 회차 기준 문항 수) |
| `TagOut` | `id*`, `name*`, `questionCount` |
| `FigureOut` | `needed`, `kind`(`diagram`\|`screen`\|null), `imageUrl`, `alt` — 전부 선택 |
| `ProgressItem` | `StateOut` 전부 + `examId*`, `number*`, `subjectCode*`, `subjectName`, `stem*` |
| `SubjectStatsOut` | `subjectCode*`, `subjectName*`, `answered*`, `correct*`, `wrong*`, `questionsTotal*`, `questionsSeen*`, `accuracyPct` |
| `WrongQuestionOut` | `questionId*`, `examId*`, `number*`, `subjectCode*`, `subjectName*`, `stem*`, `attemptCount*`, `wrongCount*`, `lastChoiceNo`, `lastIsCorrect`, `lastAnsweredAt`, `bookmarked`, `note`, `reviewDueOn` |
| `ReviewDueOut` | `questionId*`, `examId*`, `number*`, `subjectCode*`, `subjectName*`, `stem*`, `reviewDueOn*`, `overdueDays*`, `lastIsCorrect`, `wrongCount*`, `note` |

주의할 점 몇 가지:

- `SubjectStatsOut.accuracyPct` 는 **응답 기록이 없는 과목에서 `null`** 입니다(0 이 아님). `/api/stats/subjects` 는 응답이 없는 과목도 5행 전부 돌려줍니다.
- `StateOut` 자체가 `null` 일 수 있습니다 — 그 문항에 대한 행이 없을 때입니다(`study_state` 는 문항당 1행). `PATCH` 로 북마크·메모만 남긴 문항은 행이 생기므로 `state` 가 오고, 이때 `attemptCount`·`correctCount`·`wrongCount`·`streak` 는 `0`, `bookmarked` 는 보낸 값, `lastChoiceNo`·`lastIsCorrect`·`lastAnsweredAt` 은 `null` 입니다. 응답 화면에서 `state?.attemptCount ?? 0` 처럼 다루세요.
- `ReviewDueOut.overdueDays` 는 `0` 이면 오늘, 클수록 밀린 것입니다.
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
```

`GradeRequest`: `choiceNo`(필수, 1~4), `sessionId`(선택), `elapsedMs`(선택, 0 이상).
`sessionId` 는 **이미 존재하는 세션 id 여야 합니다** — 아니면 `404`. 세션 밖 단발 풀이로 기록하려면 필드를 생략하거나 `null` 로 보내세요.
이 호출은 `study_attempt` 에 1행을 넣고 `study_state` 를 갱신합니다(채점 자체가 진도 기록입니다). 그래서 `state` 가 응답에 함께 실립니다.

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

### 세션

```bash
POST /api/sessions  {"mode": "random"}                      # 201
POST /api/sessions  {"mode": "exam",   "examId": "2026-1"}  # 201
POST /api/sessions  {"mode": "subject", "subjectCode": 3}   # 201
```

`mode` 는 `exam`(회차 모의고사) · `subject`(과목 연습) · `random`(랜덤) · `review`(오답 복습) 중 하나입니다.
`mode=exam` 에 `examId` 가 없거나 `mode=subject` 에 `subjectCode` 가 없으면 `400`, 없는 회차·과목이면 `404`.
`/finish` 는 이미 끝난 세션에 다시 호출해도 현재 상태를 그대로 돌려줍니다(멱등).

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
| `400` | 규칙 위반 — 필드 없는 `PATCH`, `mode=exam` 인데 `examId` 없음 등 |
| `401` | `EXAM_API_TOKEN` 설정 시 쓰기 요청에 토큰이 없거나 틀림 |
| `404` | 없는 회차·문항·과목·세션 |
| `422` | 스키마 위반 — `choiceNo` 가 1~4 밖, `limit` 이 범위 밖 등 |
| `500` | 그 밖의 서버 오류 |
| `503` | DB 에 연결할 수 없거나 커넥션 풀이 아직 초기화되지 않음(모든 엔드포인트) |

오류 본문은 FastAPI 표준대로 `{"detail": "..."}` 이고 메시지는 한글입니다. DB 장애일 때는 `{"detail": "DB 에 연결할 수 없습니다"}` 입니다.

### DB 가 내려가 있을 때 (실측)

모든 엔드포인트가 **2초 안에 `503`** 을 돌려줍니다. 커넥션 풀 대기 시간이 `POOL_TIMEOUT`(2초, `back/app/db.py`)이라 요청이 오래 묶이지 않습니다.

| 요청 | 수정 전 | 지금 |
|---|---|---|
| `GET /api/health` | `503` 2.10초 | `503` 2.09초 |
| `GET /api/exams` | `500` 30.03초 | `503` 2.04초 |
| `GET /api/stats/subjects` | `500` 30.04초 | `503` 2.02초 |
| `POST /api/sessions`(쓰기) | `500` 30.02초 | `503` 2.02초 |

수정 전에는 데이터 엔드포인트가 풀 기본 타임아웃(30초)을 기다린 뒤 처리되지 않은 `psycopg_pool.PoolTimeout` 으로 `500 Internal Server Error` 가 되어, 프론트에서 DB 장애가 서버 버그처럼 보였습니다. 지금은 헬스체크와 같은 `503` 이고 본문도 `{"detail": "DB 에 연결할 수 없습니다"}` 로 옵니다. 조회·쓰기 엔드포인트 10개(`/api/exams`·`/api/subjects`·`/api/tags`·`/api/stats/*`·`/api/progress/*`·`/api/sessions`·`/api/questions/*/answer` 등)를 모두 호출해 `503` 과 2.00~2.09초를 확인했습니다. 이 동작은 `back/tests/test_db_unavailable.py` 가 고정합니다.

`/api/health` 는 `ping()` 이 예외를 삼키므로 DB 가 죽어 있어도 `503` + `{"status":"degraded","database":"unavailable"}` 을 돌려줍니다(동작은 수정 전과 같습니다). 커넥션 풀이 아직 만들어지지 않은 시점(앱 기동 전)도 같은 `503` 입니다.

## 5. 의존 DB 객체

전부 `app` DB 의 `ipe` 스키마입니다. DDL 은 `db/001_schema.sql`(문항)과 `db/002_progress.sql`(진도), 컬럼 의미는 `db/README.md`.

| 객체 | 종류 | 쓰는 곳 |
|---|---|---|
| `ipe.exam` | 테이블 | 회차 목록·상세, 세션 대상 검증 |
| `ipe.subject` | 테이블 | 과목 목록, 문항 조회 조인 |
| `ipe.question` | 테이블 | 문항 조회·채점, `answer`/`explanation` 은 채점 응답에만 |
| `ipe.question_choice` | 테이블 | 보기 4개, 보기별 해설(채점 응답) |
| `ipe.tag` · `ipe.question_tag` | 테이블 | 태그 목록, 태그 필터 |
| `ipe.study_session` | 테이블 | 세션 시작·종료 |
| `ipe.study_attempt` | 테이블 | 채점할 때마다 1행 append, 통계 원장 |
| `ipe.study_state` | 테이블 | 문항별 현재 상태(북마크·메모·복습 예정일·연속 정답) |
| `ipe.v_subject_stats` | 뷰 | `/api/stats/subjects` |
| `ipe.v_wrong_questions` | 뷰 | `/api/stats/wrong-questions` |
| `ipe.v_review_due` | 뷰 | `/api/stats/review-due` |

API 는 `v_wrong_questions` · `v_review_due` 에 들어 있는 `answer` 컬럼을 **SELECT 하지 않습니다**. 뷰를 직접 조회할 때와 응답이 다르니 주의하세요.

데이터 규모: 문항 1,300 / 보기 5,200 / 회차 13. 회차 간 중복 문항이 있어 고유 문항은 847개입니다(`tools/dups.py`). **`/api/questions/random` 은 중복을 걸러내지 않으므로** 같은 문항이 다른 호출에서 다시 나올 수 있습니다.

## 6. 프론트에서 붙일 때

- 개발 프론트 오리진은 `http://localhost:8091` 이 기본 허용입니다. 다른 포트·도메인이면 `EXAM_CORS_ORIGINS` 에 쉼표로 추가하세요.
- 쓰기 요청 3종(`POST /api/sessions`, `/finish`, `/answer`)과 `PATCH` 는 `EXAM_API_TOKEN` 을 설정한 경우에만 `X-Exam-Token` 헤더가 필요합니다.
- 그림은 `/figures/...` 경로로 옵니다. DB 에는 경로·`alt` 만 있고 바이너리는 없으니 API 오리진 기준으로 해석하세요.
- 타입이 필요하면 `http://127.0.0.1:8092/openapi.json` 에서 생성하세요.
- DB 장애는 모든 엔드포인트가 2초 내 `503`(`{"detail":"DB 에 연결할 수 없습니다"}`)으로 알려줍니다. 상태·사유까지 보려면 `/api/health`(2초 내 `503`, `database: "unavailable"`)를 쓰세요.

## 7. 알아둘 것

- **배포 방식은 미정입니다.** docker·systemd 어느 쪽으로 갈지 정해지지 않아, 이 문서는 로컬 실행만 다룹니다. 설정을 전부 환경변수로 받으므로 어느 쪽이든 그대로 쓸 수 있습니다.
- 쿼리 로그·요청 추적은 넣지 않았습니다. `uvicorn` 기본 로그만 나옵니다.
- 인증은 단일 사용자 전제의 공유 토큰 하나뿐입니다. 사용자별 계정·권한은 없습니다.
- `POST /api/questions/{id}/answer` 는 **채점과 진도 기록을 분리할 수 없습니다.** 정답만 확인하고 기록을 남기고 싶지 않은 경우는 지금 지원하지 않습니다.
