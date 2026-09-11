# AGENTS.md

정보처리기사 필기 기출문제 데이터셋과 PostgreSQL 적재 파이프라인, 조회·채점·진도 API(`back/`, FastAPI), 웹 화면(`front/`, Nuxt 4 + TypeScript + Tailwind CSS v4)입니다.
학습 앱(PC·모바일 하이브리드)이며, 화면은 SPA(`ssr:false`)로 `back/` 을 호출합니다.

---

## 먼저 읽을 것 (지키지 않으면 사고가 나는 것들)

- **`.env` 와 `aws/` 는 절대 커밋하지 않습니다.** `.gitignore` 에 있습니다.
  `aws/test-keypair.pem` 은 EC2 개인키입니다. 한 번 커밋되면 히스토리에서 지워도 이미 노출된 것으로 봐야 하므로, push 전에 `git status` 로 확인하세요.
- **데이터를 고친 뒤에는 반드시 두 검증을 통과시킵니다.**
  ```bash
  python tools/validate.py          # 문항 JSON 65파일 / 1,300문항
  python tools/load_db.py --verify  # DB 정합성
  ```
- **문항 JSON 을 손으로 편집하지 않습니다.** python 스크립트로 패치하고 검증기를 돌립니다.
  기존 포맷 유지: `ensure_ascii=False`, `indent=2`, 키 순서, UTF-8.
- **적재는 멱등합니다.** `tools/load_db.py` 는 몇 번을 실행해도 같은 결과입니다.

## 코딩 규칙

- **주석과 docstring 은 한글로 씁니다.** 설명하는 글은 전부 한글로 적고, 변수·함수·클래스·테이블 이름만 영어를 씁니다.
  기존 `tools/*.py`·`db/*.sql` 과 `back/`(FastAPI)·`front/`(Nuxt) 코드가 그렇게 되어 있고, 앞으로 만드는 코드에도 똑같이 적용합니다.
- 커밋 메시지도 한글로 씁니다.

## 구조

```
data/*.pdf                        원본 기출문제 13회차 (2022-1 ~ 2026-1)
data/questions/<회차>/<과목>.json   최종 문항 데이터 65파일 / 1,300문항  ← git 추적
data/figures/<회차>/<번호>.png      순수 도식 24개                      ← git 추적
data/index.json                   앱 진입점 (회차·과목·파일경로)
data/raw/<회차>.json              1차 추출 결과 (좌표 포함)
data/raw/pages/, data/raw/text/   렌더 캐시 (재생성 가능, gitignore)
db/                               000_bootstrap.sql · 001_schema.sql(문항) · 002_progress.sql(진도) · 003_study_items.sql(세션 슬롯·과목 사이클) · README.md
tools/                            파이프라인 스크립트 + 스키마 정본
back/                             조회·채점·진도·과목 사이클 API (FastAPI) — 실행법·엔드포인트는 back/README.md
front/                            학습 앱 화면 (Nuxt 4 + TypeScript + Tailwind CSS v4, SPA) — 실행법은 front/README.md
docs/                             git 에 없음 (빈 디렉터리는 추적되지 않아 clone·worktree 에 생기지 않음)
```

## 파이프라인

```
data/*.pdf
  │  python tools/extract.py                    좌표 기반 문항 추출
  ▼
data/raw/<회차>.json
  │  (문항 정리 + 해설 생성 — 서브에이전트 병렬 작업으로 만들어짐)
  ▼
data/questions/<회차>/<과목>.json
  │  python tools/build_index.py                앱 진입점 생성
  ▼
data/index.json
  │  python tools/load_db.py                    DB 적재
  ▼
PostgreSQL app.ipe
```

## 도구

| 명령 | 설명 |
|---|---|
| `python tools/extract.py` | PDF → 문항 (좌표 정렬, 2단 레이아웃 대응). `dump`/`render` 서브커맨드로 페이지 텍스트·이미지 확인 |
| `python tools/validate.py [파일...]` | 문항 JSON 검증 (스키마 + 불변식). 인자 없으면 전체 |
| `python tools/report.py` | 데이터셋 품질 리포트 (행 수·분포·잔여물) |
| `python tools/dups.py` | 회차 간·회차 내 중복 문항 행렬 |
| `python tools/build_index.py` | `data/index.json` 재생성 (자체 검증 포함) |
| `python tools/crop_figures.py <회차> <번호...>` | 그림 영역 크롭 (200dpi, `--full` 은 문항 전체) |
| `python tools/scan_figures.py` | 도형/이미지 있는 문항 탐지 |
| `python tools/load_db.py --init\|--verify` | `db/*.sql` 마이그레이션 파일명 순서로 적용(`000_bootstrap.sql` 은 superuser 전용이라 제외) / JSON 적재 / 검증 |
| `cd back && .venv/Scripts/python -m uvicorn app.main:app --port 8092` | FastAPI API 서버 기동. 최초 1회 `python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt`. 엔드포인트·환경변수는 `back/README.md` |
| `cd front && npm ci` | 프론트 의존성 설치 (npm, `package-lock.json` 고정). 최초 1회·lock 변경 시 |
| `cd front && npm run dev` | 학습 앱 dev 서버 (SPA, 8091). 접속은 `http://localhost:8091`(127.0.0.1 은 CORS 오리진이 달라 차단), 백엔드(8092)가 먼저 떠 있어야 함 |
| `cd front && npm run build` | 타입 검사(`nuxt typecheck`) + 프로덕션 빌드. 타입 오류가 있으면 실패 |
| `cd front && npm run shots` | Playwright 스크린샷 + 화면 자체 점검(콘솔 오류·가로 잘림·클릭 영역 44px). dev 서버가 없으면 자동 기동·종료, 결과는 `<저장소 루트>/tmp/shots/` |

## 문항 JSON 계약

정본: `tools/question.schema.json`. 경로는 모두 **`data/` 기준 상대경로 + 슬래시**입니다.

```json
{
  "id": "2026-1-064", "number": 64, "subjectCode": 4,
  "stem": "질문 문장만",
  "passage": "코드/표/지문 (없으면 null)", "passageKind": "code|table|text|null",
  "choices": [{"no":1,"text":"..."}], "answer": 2,
  "explanation": "해설", "choicesAnalysis": [{"no":1,"correct":false,"why":"..."}],
  "keyPoint": "핵심 개념", "tags": ["..."], "difficulty": 2,
  "figure": {"needed":false,"kind":"diagram|screen|null","image":"figures/2026-1/099.png","alt":"...","page":8,"col":1,"box":[57.5,90.5,246.3,213.3]},
  "source": {"pdf":"...","page":5},
  "provenance": {"answer":"pdf|derived","explanation":"pdf|generated"}
}
```

규칙:
- 보기·`choicesAnalysis` 는 각각 정확히 4개, `correct` 는 정확히 1개이며 `answer` 와 일치해야 합니다.
- `passage` 와 `passageKind` 는 둘 다 null 이거나 둘 다 값이 있어야 합니다.
- 과목은 번호로 고정: 1=소프트웨어 설계(1~20), 2=소프트웨어 개발(21~40), 3=데이터베이스 구축(41~60), 4=프로그래밍 언어 활용(61~80), 5=정보시스템 구축 관리(81~100).

## 자료 처리 정책 (확정 사항)

- **표는 텍스트로 복원합니다.** `passage` + `passageKind:"table"`, 행은 줄바꿈·열은 ` | ` 구분. 보기가 표인 경우도 텍스트로.
- **코드도 텍스트입니다.** `passage` + `passageKind:"code"`, 줄바꿈·들여쓰기 유지.
- **이미지는 순수 도식(트리·그래프·순서도·망 구성도·UML·화면 목업)만.** `figure.needed=true`, `kind` 는 `diagram`/`screen`, `alt` 필수.
- 그림 바이너리는 DB 에 넣지 않습니다. 파일로 서빙하고 DB 에는 경로·alt·좌표만 둡니다.
- 다크모드 대응은 하지 않습니다(흰 배경 고정).

## DB

- `app` 데이터베이스의 **`ipe` 스키마**. 소유자·접속 계정 모두 **`yangyag`** (기존 앱과 동일 계정).
- **진도 관리 테이블이 있습니다.** `study_session`·`study_cycle`·`study_session_item`·`study_attempt`·`study_state` + 통계 뷰 3종(`v_subject_stats`·`v_wrong_questions`·`v_review_due`), DDL 은 `db/002_progress.sql`(진도)·`db/003_study_items.sql`(세션 슬롯·과목 사이클).
  적용은 별도 명령 없이 `python tools/load_db.py --init` 이 `db/*.sql` 을 파일명 순서로 전부 실행합니다(`000_bootstrap.sql` 은 superuser 전용이라 제외). **`--init` 은 전체가 한 트랜잭션이라 중간 실패 시 전부 롤백됩니다** — 기록이 있는 DB에 처음 적용할 때의 주의사항은 `db/README.md` 의 경고 1. 컬럼 의미·조회 예시는 `db/README.md`.
- `app` 안의 `english` / `english_test` 스키마는 기존 영어 앱 것입니다. **절대 건드리지 않습니다.**
- **`yangyag` 의 `search_path` 는 `english, public` 입니다.** 역할 전역 설정을 바꾸면 기존 앱이 영향받으므로 건드리지 마세요. `ipe` 를 쓰려면 스키마를 한정하거나(`ipe.question`) 접속 시 지정합니다:
  `?options=-csearch_path%3Dipe,public` (`tools/load_db.py` 는 세션 search_path 를 스스로 고정합니다)
- 접속 정보는 `.env` (gitignore). `tools/load_db.py` 가 `EXAM_DB_URL` → `DATABASE_URL` → libpq `PG*` → 기본값 순으로 찾습니다.
- EC2 이식: **저장소를 받고 `db/000_bootstrap.sql` → `load_db.py --init` → `load_db.py` 만** 하면 됩니다. PDF 재추출 불필요. 자세한 절차는 `db/README.md`.

## 알아둘 함정

1. **번들된 `pdftotext`(xpdf 4.00)로는 한글이 안 뽑힙니다** — 영문·숫자만 나오고 한글은 공백이 됩니다. PDF 텍스트는 PyMuPDF(`pymupdf`) 로 뽑으세요.
2. **이 PDF들은 2단 레이아웃이고 텍스트가 그려진 순서가 뒤섞여 있습니다.** `page.get_text()` 를 그대로 쓰면 문항 순서가 깨집니다. `tools/extract.py` 의 좌표 정렬(단 → y → x)을 쓰세요.
3. **회차 간 중복 문항이 많습니다.** 수치는 세는 기준에 따라 다르니 쓰는 곳의 기준을 확인하세요. **API 내용 키 기준**(`back/app/queries.py` 의 `content_key` — 랜덤 출제·과목 사이클 구성에 쓰는 기준)으로 1,300문항은 **938그룹**이고, 과목별 고유 문항 수는 176·194·194·199·181(1~5과목, 각 260문항)입니다(`GET /api/subject-cycles/overview` 의 `uniqueQuestionCount`). **`tools/dups.py` 기준**(더 느슨한 정규화)은 고유 문항 **847개**입니다. 랜덤 출제의 중복 제거는 API(`/api/questions/random`)가 내용 키(stem + 지문 + 보기 4개 + 도식)로 처리합니다 — 그룹마다 1문항, 대표는 무작위, 고유 후보가 `count` 보다 적으면 가용분만 반환. 쉼표는 자연어 문장부호일 때만 무시하고(2023-1-001·2023-1-023 같은 인쇄 차이), `code`/`table` 지문의 쉼표와 공백 없이 영숫자에 붙은 코드·수식 쉼표는 보존합니다(`back/app/queries.py` 의 `key_text`·`code_key_text`). 목록·단건 조회는 원본 그대로입니다.
4. **소스 PDF 자체의 결함**이 있습니다. `2023-1` 은 1번=23번, `2023-2` 는 40번=61번이 같은 문항이고, `2022-2` 5번은 정답표에 정답이 없습니다(그래서 `provenance.answer="derived"`). 고치지 말고 그대로 두세요.
5. **검증기의 공백 검사는 `isinstance` 로 합니다.** 과거에 `str(None)` 이 `"None"` 이 되어 누락을 통과시킨 버그가 있었습니다(2023-1 3과목 `why` 20건 누락).
6. **줄바꿈**: 저장소는 `core.autocrlf` 가 켜져 있어 작업 트리는 CRLF 입니다. JSON 패치 시 기존 포맷을 유지하세요.

## 환경

- Windows + Git Bash. Python 3.14 (`psycopg[binary]`, `pymupdf` 설치됨).
- PostgreSQL 은 docker 컨테이너 `postgres` (17.10) 로 5432 에 떠 있습니다. 호스트에 `psql` 이 없어서 관리 명령은 `docker exec -i postgres psql -U postgres -d app` 로 실행합니다.
- **프론트(`front/`)는 Nuxt 4 + TypeScript + Tailwind CSS v4 SPA(`ssr:false`)입니다.** 패키지 매니저는 npm(`package-lock.json`)이고 pnpm 은 쓰지 않습니다.
- **프론트 dev 서버는 8091, 접속 주소는 `http://localhost:8091` 입니다.** 백엔드 기본 CORS 허용 오리진이 이 값이라 `127.0.0.1:8091` 은 오리진 문자열이 달라 API 가 막힙니다. API 오리진은 `NUXT_PUBLIC_API_BASE`(기본 `http://127.0.0.1:8092`)로 바꿉니다.
- 콘솔이 cp949 라 한글 출력이 깨집니다. 스크립트 출력을 확인할 때는 `PYTHONIOENCODING=utf-8` 을 붙이거나 파일로 리다이렉트해 읽으세요.
