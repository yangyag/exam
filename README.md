# 정보처리기사 필기 학습 앱 (exam)

정보처리기사 필기 기출문제 13회차(2022-1 ~ 2026-1)를 **과목별 사이클 · 회차별 연습 · 모의고사**로 풀고, 채점·해설·진도·통계까지 한 곳에서 보는 개인 학습 앱입니다.

- 기출문제 PDF 13개를 좌표 기반으로 추출해 **문항 JSON 65파일 / 1,300문항**으로 정리하고(그림 24개는 PNG), 그 데이터를 PostgreSQL 에 적재합니다.
- 화면(Nuxt 4 SPA)은 백엔드(FastAPI)만 호출합니다. PC·모바일 브라우저에서 같은 화면을 씁니다.
- 운영: **https://yangyag5.duckdns.org** (EC2 + 도커, 단일 사용자 · 별도 로그인 없음)

---

## 1. 무엇이 들어 있나

| 영역 | 내용 |
|---|---|
| 데이터 | 회차 13 · 문항 1,300 · 보기 5,200 · 태그 1,281 · 문항-태그 3,347 · 그림 24 |
| 백엔드 | FastAPI + PostgreSQL(`app` DB 의 `ipe` 스키마). 엔드포인트 26개(경로 23개) — 조회 · 채점 · 진도 · 세션 · 과목 사이클 |
| 프론트 | Nuxt 4 + TypeScript + Tailwind CSS v4 (SPA, `ssr:false`) — 라우트 5개: 홈 · 연습 · 회차 선택 · 모의고사 · 이전 결과 |
| 파이프라인 | PDF → 1차 추출(`data/raw`) → 문항 JSON(`data/questions`) → 앱 진입점(`data/index.json`) → DB |
| 검증 | 문항 JSON 스키마 검증 · DB 정합성 검증 · 백엔드 테스트 198개 · Playwright 화면 점검 13단계·62컷 (2026-09-14 기준, 정본 `plan/test-cases.md`) |
| 배포 | 로컬에서 linux/amd64 이미지 2종 빌드 → tar 전송 → EC2 `docker load` → compose 재기동 |

### 고유 문항 수

회차 간 중복이 많아 "몇 문제나 새로운가"는 세는 기준에 따라 다릅니다.

- **API 기준**(내용 키 = 지문 + 보기 4개 + 도식): 1,300문항 → **938그룹**. 과목별 고유 문항 176 / 194 / 194 / 199 / 181.
- **`tools/dups.py` 기준**(더 느슨한 정규화): 고유 문항 **847개**.

랜덤 출제·과목 사이클은 API 기준(내용 키)으로 중복을 제거합니다.

---

## 2. 구조 한눈에

```
data/*.pdf  (기출문제 원본 13개)
   │  tools/extract.py                 좌표 정렬 추출 (2단 레이아웃 대응)
   ▼
data/raw/<회차>.json                    1차 추출 결과 (좌표 포함)
data/raw/_figures.json                  도형/이미지 탐지 결과 (tools/scan_figures.py)
   │  문항 정리 + 해설 생성
   ▼
data/questions/<회차>/<과목>.json        65파일 / 1,300문항  ← git 추적
   │  tools/build_index.py
   ▼
data/index.json                         앱 진입점 (회차·과목·파일경로)
   │  tools/load_db.py
   ▼
PostgreSQL  app DB → ipe 스키마 (문항 · 보기 · 태그 · 진도)
   │
   ├── back/   FastAPI  :8092   조회 · 채점 · 진도 · 세션 · 과목 사이클
   └── front/  Nuxt SPA :8091   화면 5개(라우트 기준, 점검 스크린샷 상태 13종) → back 호출 (SPA 는 API 만 본다)
                                  │
                            deploy/  EC2 도커 (호스트 nginx TLS → exam-front → exam-back → 공용 postgres)
```

---

## 3. 기술 스택 · 환경

| 구분 | 사용 |
|---|---|
| 백엔드 | Python 3.13 이상(로컬 3.14.7 확인, 도커 이미지는 `python:3.13-slim`), FastAPI 0.141, uvicorn, psycopg 3.3(`[binary,pool]`), pydantic 2.13 |
| 프론트 | Node 22(도커 이미지)·24(로컬), Nuxt 4.5, Vue 3.5, TypeScript 5.9, Tailwind CSS 4.3, Playwright 1.63 |
| DB | PostgreSQL 17 (로컬은 도커 컨테이너 `postgres`, 운영은 공용 `yangyag-postgres`) |
| 데이터 도구 | Python + PyMuPDF(`pymupdf` 1.28.2 설치됨), 표준 라이브러리 |
| 실행 환경 | Windows + Git Bash (개발), Ubuntu EC2 (운영) |

```bash
# 의존성
cd back && python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
cd front && npm ci
python -m pip install pymupdf      # 미설치일 때만 (현재 1.28.2 설치돼 있음)
```

---

## 4. 디렉터리

| 경로 | 설명 |
|---|---|
| `data/` | 기출문제 PDF · 문항 JSON · 그림 PNG · `index.json` (문항 데이터의 정본) |
| `db/` | 스키마 DDL 5종(`000_bootstrap` ~ `004_session_comments`) + 설명 |
| `tools/` | 추출 · 검증 · 적재 파이프라인 스크립트 |
| `back/` | FastAPI 앱(`app/`)과 테스트(`tests/`) |
| `front/` | Nuxt 앱(`app/pages`·`components`·`composables`)과 화면 점검 스크립트 |
| `deploy/` | Dockerfile 2종 · `docker-compose.yml` · nginx 설정 · `deploy.sh` |
| `plan/` | `test-cases.md` — 릴리스 전후에 돌리는 테스트 케이스와 실행 기록 |
| `aws/` | EC2 접속 스크립트와 개인키 (**커밋 금지**, gitignore) |
| `tmp/` | 스크린샷·로그 등 임시 산출물 (gitignore) |
| `docs/` | 설계 문서 자리 — git 미추적 빈 디렉터리(clone·worktree 에는 생기지 않음) |
| `AGENTS.md` | 저장소 작업 규칙(코딩 규칙 · 자료 처리 정책 · 함정) |

---

## 5. 빠른 시작 (로컬)

전제: `git clone git@github.com:yangyag/exam.git`, Docker(로컬 `postgres` 컨테이너 17), Python 3.13 이상(로컬 3.14.7 확인, 도커 이미지는 `python:3.13-slim`), Node 22 이상. 아래 명령은 저장소 루트에서 실행합니다.

### 1) DB 준비

```bash
# app 데이터베이스와 도커 컨테이너 postgres(17, 127.0.0.1:5432)가 이미 있다고 가정
# 1) 역할(yangyag)·스키마(ipe)·확장(pg_trgm) — superuser 로 1회, 여러 번 실행해도 안전
docker exec -i postgres psql -U postgres -d app -f - < db/000_bootstrap.sql

# 2) 저장소 루트 .env (gitignore) — 템플릿은 .env.example
#   EXAM_DB_URL=postgresql://yangyag:<비밀번호>@localhost:5432/app
#   (.env.example 과 같은 형식. `?options=-csearch_path%3Dipe,public` 는 없어도 됩니다 —
#    back/ 앱과 tools/load_db.py 가 접속 세션의 search_path 를 ipe,public 으로 스스로 고정)

# 3) 마이그레이션 → 적재 → 검증 (멱등, 몇 번을 실행해도 같은 결과)
python tools/load_db.py --init     # db/001_schema → 002_progress → 003_study_items → 004_session_comments 적용 (적재 없음)
python tools/load_db.py            # data/questions 적재 (멱등)
python tools/load_db.py --verify   # 문항·보기·태그·그림 수와 정합성 확인
```

`000_bootstrap.sql` 은 superuser 권한과 psql 메타명령이 필요해 `--init` 에서는 제외되고, 새 SQL 파일을 `db/` 에 추가하면 다음 `--init` 부터 자동으로 포함됩니다. 자세한 절차는 `db/README.md`.

### 2) 백엔드 (8092)

```bash
cd back && .venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8092 --reload
curl http://127.0.0.1:8092/api/health      # {"status":"ok","database":"ok",...}
```

API 문서는 `http://127.0.0.1:8092/docs`, 계약은 `back/README.md`.

### 3) 프론트 (8091)

```bash
cd front && npm run dev        # http://localhost:8091  ← 127.0.0.1 은 CORS 오리진이 달라 막힘
```

---

## 6. 화면과 학습 흐름

| 화면 | 경로 | 하는 일 |
|---|---|---|
| 홈 | `/` | 과목 5개 카드(진행도·정답 수·상태) + 회차별 연습·모의고사 진입점 |
| 연습 | `/sessions/{id}` | 문항 제출 즉시 채점 → 해설·보기별 해설 → 다음 문항. 오답이면 보기별 해설 자동 펼침 |
| 회차 선택 | `/exams` | 13회차 목록에서 회차 연습(문항마다 즉시 채점) 또는 모의고사(제한시간 없음) 선택 |
| 모의고사 | `/exam/{id}` | 정답 비공개로 풀고 문항 번호 그리드로 이동 → 최종 제출(미응답 강조) → 결과·문항별 해설 |
| 이전 결과 | `/history` | 과목별 최근 사이클(라운드별 문항·정답·시각)과 회차 세션(응답/문항·제출 시각·합격 여부) |

**과목 사이클** — 과목을 시작하면 그 과목의 고유 문항을 무작위 순서로 한 바퀴 돕니다(1라운드). 라운드의 마지막 문항을 채점할 때 오답이 있으면 오답만 모은 복습 라운드가 자동으로 열리고, 전부 맞히면 사이클이 완료됩니다. 과목당 진행 중 사이클은 1개이고, 두 기기에서 동시에 시작하면 한쪽만 만들어집니다(409).

**모의고사 채점** — 100문항 중 응답한 것만 원장(`study_attempt`)에 남기고 미응답은 점수상 0점으로 계산합니다(미응답은 진도 누계에 남기지 않음). 합격 기준은 과목 40점 이상 + 전 과목 평균 60점 이상.

---

## 7. 파이프라인과 도구

```bash
python tools/extract.py            # PDF → 문항 (좌표 정렬). dump/render 서브커맨드로 페이지 확인
python tools/validate.py [파일...]  # 문항 JSON 검증 (스키마 + 불변식). 인자 없으면 전체 65파일
python tools/report.py             # 데이터셋 품질 리포트 (행 수·분포·잔여물)
python tools/dups.py               # 회차 간·회차 내 중복 문항 행렬
python tools/build_index.py        # data/index.json 재생성 (자체 검증 포함)
python tools/crop_figures.py <회차> <번호...>   # 그림 영역 크롭 (200dpi, --full 은 문항 전체)
python tools/scan_figures.py       # 도형/이미지가 있는 문항 탐지
python tools/load_db.py --init     # db/*.sql 마이그레이션 적용 (000_bootstrap.sql 제외, 적재 없음)
python tools/load_db.py            # data/questions 적재 + 검증 (멱등)
python tools/load_db.py --verify   # 적재 결과 검증만
```

문항 JSON 계약(정본 `tools/question.schema.json`)과 자료 처리 정책은 `AGENTS.md` 에 정리돼 있습니다. 요점:

- 표는 텍스트로 복원(`passageKind: "table"`, 행은 줄바꿈 · 열은 ` | `), 코드도 텍스트(`"code"`, 줄바꿈·들여쓰기 유지).
- 그림은 **순수 도식**(트리·그래프·순서도·망 구성도·UML·화면 목업)만 PNG 로 두고, DB 에는 경로·alt·좌표만 저장합니다.
- 소스 PDF 자체의 결함(2023-1 은 1번=23번, 2023-2 는 40번=61번, 2022-2 5번은 정답표 누락)은 고치지 않고 그대로 둡니다.

---

## 8. 백엔드 API 요약

| 그룹 | 엔드포인트 |
|---|---|
| 상태 | `GET /api/health` |
| 기준 정보 | `GET /api/subjects` · `GET /api/exams` · `GET /api/exams/{id}` · `GET /api/exams/{id}/questions` · `GET /api/tags` |
| 문항·채점 | `GET /api/questions/{id}` · `GET /api/questions/random` · `POST /api/questions/{id}/answer` |
| 세션 | `POST /api/sessions` · `GET /api/sessions` · `GET /api/sessions/{id}` · `GET /api/sessions/{id}/items/{seq}` · `PUT /api/sessions/{id}/items/{seq}/answer` · `POST /api/sessions/{id}/submit` · `POST /api/sessions/{id}/finish` |
| 과목 사이클 | `POST /api/subject-cycles` · `GET /api/subject-cycles` · `GET /api/subject-cycles/overview` · `GET /api/subject-cycles/{id}` |
| 진도·통계 | `GET`·`PATCH /api/progress/questions/{id}` · `GET /api/progress/questions` · `GET /api/stats/subjects` · `GET /api/stats/wrong-questions` · `GET /api/stats/review-due` |
| 그림 | `GET /figures/<회차>/<번호>.png` |

- 정답·해설은 **제출 전에는 내려보내지 않습니다**(모의고사 진행 중 `isCorrect` 는 `null`).
- DB 가 없으면 DB 를 쓰는 엔드포인트가 2초 안에 `503` 을 돌려주고, 프론트는 안내 화면으로 전환합니다.
- 쓰기 API 는 `EXAM_API_TOKEN` 을 설정한 경우에만 `X-Exam-Token` 헤더를 요구합니다(기본은 인증 없음).

---

## 9. 테스트·검증

```bash
# 데이터
python tools/validate.py && python tools/load_db.py --verify

# 백엔드 (198개 = DB 없이 163 + 실제 DB 35, 2026-09-14 기준 — 정본은 plan/test-cases.md)
cd back && .venv/Scripts/python -m pytest -q
.venv/Scripts/python -m pytest -q -m "not integration"
.venv/Scripts/python -m pytest -q -m integration      # .env 의 TEST_DB_URL 사용 권장

# 프론트 (타입 검사 + 빌드, 화면 점검 13단계 + 스크린샷 62컷(2026-09-14 기준) → tmp/shots/)
cd front && npm run build
npm run shots                                          # 백엔드(8092)가 떠 있어야 함
```

- 통합 테스트는 `TEST_DB_URL`(테스트 전용 DB, 예: `app_test`)이 있으면 그 DB 로 붙고, 없으면 앱 DB 를 쓰되 진행 중인 사이클이 있는 과목은 건너뜁니다(사용자 기록 보호). 접속 정보가 아예 없으면 통합 35개는 skip 이고 나머지 163개가 통과합니다.
- 릴리스 전후에 돌리는 케이스 목록과 실행 기록은 `plan/test-cases.md`.

---

## 10. 운영 배포

```
인터넷 → 호스트 nginx (yangyag5.duckdns.org, TLS/certbot)
          └→ exam-front 컨테이너 (nginx, 127.0.0.1:8091)
               ├ 정적 파일: Nuxt SPA
               └ /api · /figures → exam-back 컨테이너 (uvicorn 8092)
                                       └→ yangyag-postgres (공용, app DB 의 ipe 스키마)
```

```bash
./deploy/deploy.sh                 # 빌드(linux/amd64) → tar → EC2 전송 → docker load → compose 재기동
./aws/connect.sh "cd /home/ubuntu/exam && docker compose ps"    # 운영 상태 확인
```

- 같은 오리진 구성이라 **CORS 설정과 쓰기 토큰이 필요 없습니다.**
- 재배포는 덮어쓰기 전에 직전 이미지를 `before-<타임스탬프>` 태그로 보존합니다(롤백 지점). 절차는 `deploy/README.md`.
- 운영 DB 는 공용 컨테이너 안 `app` 데이터베이스의 `ipe` 스키마입니다(기존 앱 스키마와 공존). 문항 데이터에 `TRUNCATE/DROP` 금지(진도 테이블만 초기화 가능).
- **운영 DB 최초 구축·스키마 변경은 덤프 복원이 표준**입니다(절차는 `deploy/README.md` §1). `tools/load_db.py --init` 은 로컬·신규 구축 경로이고, `db/000_bootstrap.sql` 은 `app` DB명이 하드코딩돼 있어(30행 `GRANT CONNECT ON DATABASE app`) DB 이름이 `app` 이 아닌 곳에 쓸 때는 대상 DB명으로 바꿔야 합니다.

---

## 11. 문서 색인

| 문서 | 내용 |
|---|---|
| `AGENTS.md` | 저장소 작업 규칙 — 코딩 규칙(주석·커밋은 한글) · 자료 처리 정책 · 알아둘 함정 |
| `back/README.md` | API 계약(엔드포인트·요청/응답) · 실행법 · 테스트 방법 · 환경변수 |
| `front/README.md` | 화면 구성 · 실행법 · 스크립트 · 화면 점검이 확인하는 것 |
| `db/README.md` | `ipe` 스키마 테이블 · 진도 관리 구조 · 조회 예시 · EC2 이식 절차 |
| `deploy/README.md` | 최초 배포 절차 · 재배포 · 롤백 · 주의사항 |
| `plan/test-cases.md` | 릴리스 체크리스트와 테스트 케이스 · 실행 기록 |
| `tools/question.schema.json` | 문항 JSON 스키마 정본 |

---

## 12. 알아둘 점

- **로그인 없음** — 이 앱에는 인증이 없습니다. 주소를 아는 사람은 누구나 쓸 수 있으므로 필요하면 호스트 nginx 에 Basic Auth 를 추가합니다.
- **`.env` 와 `aws/` 는 절대 커밋하지 않습니다.** `aws/test-keypair.pem` 은 EC2 개인키입니다.
- `app` DB 안의 다른 앱 스키마(로컬 `english` / `english_test`, 운영 `english`·`house`)는 **건드리지 않습니다.** `yangyag` 역할의 `search_path` 도 `app` DB 한정 설정(`ALTER ROLE ... IN DATABASE app`, 값은 `english, public` — 로컬·운영 모두)이라 바꾸지 않습니다 — 앱은 접속할 때 세션 단위로 `ipe,public` 을 지정합니다.
- 이 저장소의 PDF 는 2단 레이아웃이고 텍스트가 그려진 순서가 뒤섞여 있어, `page.get_text()` 를 그대로 쓰면 문항 순서가 깨집니다. `tools/extract.py` 의 좌표 정렬을 쓰세요.
- 콘솔이 cp949 인 Windows 에서 한글 출력이 깨지면 `PYTHONIOENCODING=utf-8` 을 붙이거나 파일로 넘겨 읽습니다.
- 다크모드 대응은 하지 않습니다(흰 배경 고정).
