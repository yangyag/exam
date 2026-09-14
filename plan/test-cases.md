# 테스트 케이스 (에이전트가 직접 실행하는 것)

작성: 2026-09-12. 목적: **릴리스·재배포 전후에 에이전트가 스스로 돌려 확인할 수 있는 케이스**를 한 곳에 모은다.
사람만 판단할 수 있는 것(디자인 선호·문구 톤)은 스크린샷으로 넘기고, 여기서는 기계적으로 판정 가능한 것만 다룬다.

대상: `tools/`(데이터·도구) · `back/`(API) · `front/`(화면) · `deploy/`(운영) · 운영 사이트

## 0. 사전 준비

| 무엇 | 명령·주소 |
|---|---|
| 백엔드(로컬) | `cd back && ./.venv/Scripts/python -m uvicorn app.main:app --port 8092` |
| 프론트(로컬) | `cd front && npm run dev` → `http://localhost:8091` (CORS 는 `localhost:8091` 만 허용) |
| 프론트 점검 전제 | `npm run shots` 는 **백엔드(8092)가 떠 있어야 한다** — 없으면 `isServerUp` 검사에서 기동 안내 후 exit 1 |
| 통합 테스트 전제 | `TEST_DB_URL`(전용 `app_test`) 준비 필요 — 만드는 절차는 `back/README.md` §1 「테스트」 |
| 로컬 DB | `docker exec -i postgres psql -U yangyag -d app` |
| EC2 DB | `docker exec -i yangyag-postgres psql -U auto -d exam` (SSH: `./aws/connect.sh`) |
| 운영 | `https://yangyag5.duckdns.org` |
| 스크린샷 | `tmp/shots/` (기본 경로, `SHOTS_DIR` 로 변경 가능 · gitignore) — Playwright 캡처는 `npx playwright screenshot` |

**공통 원칙**
- 검증이 만든 진도 행(`study_*`)은 **끝나고 지워 0행으로 복원**한다. 사용자가 만든 행은 건드리지 않는다.
- 운영 DB 는 공용 컨테이너 안의 `exam` 데이터베이스다 — `TRUNCATE/DROP` 은 진도 테이블에만, 문항 데이터에는 금지.
- 실패를 발견하면 케이스 번호·명령·기대값·실제값을 그대로 기록한다.

## 1. 데이터·도구 (`tools/`)

| # | 케이스 | 명령 | 기대 |
|---|---|---|---|
| 1-1 | 문항 JSON 검증 | `python tools/validate.py` | 65파일 / 1,300문항 / **오류 0** |
| 1-2 | 마이그레이션 멱등 | `python tools/load_db.py --init` ×2 | 두 번 모두 exit 0, 오류 없음(000 제외 001~004 적용). **`--init` 은 적재를 하지 않는다** — 적재는 `python tools/load_db.py`(적재+검증)가 한다 |
| 1-3 | 적재 정합 | `python tools/load_db.py`(적재+검증) → `python tools/load_db.py --verify` | **도구가 단언하는 값**: 회차 13 · 과목 5 · 문항 1,300 · 보기 5,200(문항×4) · 그림 24/24 + 정합성 검사 7종 0건. **눈으로 확인하는 값**: 태그 1,281(출력만, 단언 없음) · trgm 인덱스 2개(`pg_indexes` 직접 조회) |
| 1-4 | 인덱스 재생성 | `python tools/build_index.py` | "이상 없음" rc=0. **실행 후 `git checkout -- data/index.json`**(generatedAt churn) |
| 1-5 | 품질 리포트 | `python tools/report.py` | 잔여물 0, 분포 출력에 오류 없음 |
| 1-6 | 중복 분석 | `python tools/dups.py` | 고유 문항 수 리포트(도구 기준 847) |
| 1-7 | cp949 방어 | `PYTHONIOENCODING` 없이 `python tools/load_db.py --init 2>&1 \| tail -3` | UnicodeEncodeError 없이 rc=0 (2026-09-12 수정) |
| 1-8 | PDF 도구 | `python -c "import fitz"` 후 `python tools/scan_figures.py` | pymupdf 1.28.2 설치됨 — 실행해 결과 확인(없을 때만 `python -m pip install pymupdf`) |

## 2. 백엔드 (`back/`)

### 2-1. 자동 테스트

| # | 명령 | 기대 |
|---|---|---|
| 2-1-1 | `pytest -q` | **198 passed**(= 163 단위 + 35 통합, 2026-09-14 기준) |
| 2-1-2 | `pytest -q -m integration` | 35 passed(실 PostgreSQL `ipe`) |
| 2-1-3 | `pytest -q -m "not integration"` | 163 passed |
| 2-1-4 | `.env` 없이 `pytest -q` | 통합은 skip, 나머지 통과(접속 정보 부재 처리) |

### 2-2. API 계약 (실서버 호출 또는 TestClient, 만든 행은 삭제)

| # | 케이스 | 호출 | 기대 |
|---|---|---|---|
| 2-2-1 | 헬스 | `GET /api/health` | 200 `{"status":"ok","database":"ok","dbUrlSource":"EXAM_DB_URL (.env)"}` (3키) |
| 2-2-2 | 과목·회차 | `GET /api/subjects`, `/api/exams`, `/api/exams/2026-1` | 5과목 / 13회차(연도·회차 내림차순) / 과목 5 |
| 2-2-3 | 회차 문항 | `GET /api/exams/2026-1/questions?limit=200` | 100문항, 번호 오름차순 |
| 2-2-4 | 단발 채점 | `POST /api/questions/2026-1-001/answer {choiceNo}` | 200 `answer·explanation·keyPoint·choicesAnalysis` |
| 2-2-5 | 단발 채점 오류 | 없는 문항 / `choiceNo` 누락·범위 밖 | 404 / 400·422 |
| 2-2-6 | 세션 생성(연습) | `POST /api/sessions {mode:'subject'}` | **400**(사이클 API 로만) |
| 2-2-7 | 세션 생성(회차 연습) | `POST /api/sessions {mode:'exam_practice', examId:'2026-1'}` | 201 + 슬롯 100(번호순), `subjectCode` 미저장 |
| 2-2-8 | 세션 생성(중복) | 같은 회차로 다시 | 409, `replaceActive:true` 면 201 + 이전 세션 `abandoned` |
| 2-2-9 | 세션 생성 오류 | `examId` 누락 / 없는 회차 | 400 / 404 |
| 2-2-10 | 세션 단건 | `GET /api/sessions/{id}` | `itemCount·answeredCount·nextSeq` + 슬롯 목록 |
| 2-2-11 | 문항 조회(연습) | `GET /api/sessions/{id}/items/1` | 제출 전 `answer·explanation` 키 없음, `result` null |
| 2-2-12 | 문항 조회(모의고사) | 진행 중 `…/items/1` | `isCorrect` null(정답 비노출) |
| 2-2-13 | 연습 제출 | `PUT …/items/1/answer {choiceNo}` | 200 채점 응답 + `session`·`roundResult`(마지막일 때) |
| 2-2-14 | 연습 재전송 | 같은 보기 다시 | 200, `study_attempt` 행 불변 |
| 2-2-15 | 연습 재전송(다른 보기) | 다른 `choiceNo` | 409 |
| 2-2-16 | 중단 세션 제출 | `replaceActive` 로 중단된 세션에 제출 | 409 + "중단된 …" 안내 |
| 2-2-17 | 이어풀기 | 채점 후 `GET /api/sessions/{id}` | `nextSeq` = 미채점 최소 seq |
| 2-2-18 | 모의고사 선택 저장 | `PUT …/items/{seq}/answer {choiceNo}` | 200 `{seq, choiceNo, answeredAt}` (정답 없음) |
| 2-2-19 | 모의고사 선택 해제 | `{choiceNo: null}` | 200, `nextSeq` 가 그 문항으로 되돌아감 |
| 2-2-20 | 제출 뒤 저장 | 제출 후 `PUT …/answer` | 409 |
| 2-2-21 | 모의고사 제출 | `POST /api/sessions/{id}/submit` | 200 `bySubject[5]·averageScore·passed·unansweredCount` |
| 2-2-22 | 미응답 규칙 | 일부만 선택 후 제출 | `unansweredCount` 정확, `study_attempt` 는 **응답한 수만큼만** |
| 2-2-23 | 재제출 멱등 | 같은 세션에 다시 submit | 200 같은 본문, 원장 불변 |
| 2-2-24 | 제출 오류 | 비-exam 세션 / 중단 세션 / 없는 세션 | 400 / 409 / 404 |
| 2-2-25 | 과목 사이클 생성 | `POST /api/subject-cycles {subjectCode:1}` | 201 + 라운드1 세션(고유 문항 수만큼 슬롯) |
| 2-2-26 | 사이클 중복·재구성 | 같은 과목 다시 / `replaceActive:true` | 409 / 201 + 기존 `abandoned` |
| 2-2-27 | 홈 요약 | `GET /api/subject-cycles/overview` | 5과목, 상태 4종, `uniqueQuestionCount` 176/194/194/199/181 |
| 2-2-28 | 사이클 상세·목록 | `GET /api/subject-cycles/{id}`, `GET /api/subject-cycles` | 라운드 목록(문항·정답 수·시각) / 필터·페이지 |
| 2-2-29 | 라운드 자동 전환 | 라운드의 마지막 슬롯 채점 | 오답 있으면 `review` 라운드 생성, 없으면 사이클 `completed` |
| 2-2-30 | 슬롯 세션 finish | `POST /api/sessions/{id}/finish` | 409(슬롯 세션은 자동 종료·submit 사용) |
| 2-2-31 | 진행·통계·태그 | `GET /api/progress/questions/…`, `/api/stats/*`, `/api/tags` | 200, 기존 계약 유지 |
| 2-2-32 | 그림 서빙 | `GET /figures/2026-1/099.png` | 200 PNG |

### 2-3. 동시성 (실 PostgreSQL)

| # | 케이스 | 기대 |
|---|---|---|
| 2-3-1 | 같은 보기 동시 제출 | 원장 1행, 두 요청 모두 200 |
| 2-3-2 | 다른 보기 동시 제출 | 하나만 기록, 뒤 요청 409 |
| 2-3-3 | 같은 (mode, 회차) 동시 생성 | 하나는 409(유니크 인덱스 경합) |
| 2-3-4 | 마지막 슬롯 제출 vs 새로 구성 | 중단된 사이클에 열린 라운드 1개, 그 라운드 채점 시 자동 회복 |
| 2-3-5 | 모의고사 제출 vs 선택 저장 | 제출 뒤 도착한 저장은 409 |

## 3. 프론트 (`front/`)

| # | 케이스 | 명령 | 기대 |
|---|---|---|---|
| 3-1 | 타입·빌드 | `npm ci && npm run build` | 타입 오류 0 + 빌드 성공 |
| 3-2 | 자체 점검·캡처 | `npm run shots` | **모든 점검 통과**(2026-09-14 기준 13단계·62컷·exit 0 — 컷 수는 실행 시점 값): 콘솔 오류 0 · 가로 잘림 0 · 클릭 영역 44px · 키보드 조작 · 409 안내 · 정답 비노출 |
| 3-3 | 스크린샷 육안 | `tmp/shots/`(기본, `SHOTS_DIR` 로 변경 가능) | 홈 · 연습(코드·표·도식) · 모의고사(그리드·제출 대화상자) · 결과 · 이력 · 오류 4종 · 모바일 375px |
| 3-4 | 과목 연습 흐름 | 홈 `시작하기` → 연습 화면 → 3문항 제출 | 채점·해설 표시, 진행도 갱신 |
| 3-5 | 오답 자동 펼침 | 오답 제출 / 정답 제출 | 오답이면 보기별 해설 **펼쳐짐**, 정답이면 접힘(토글 유지) |
| 3-6 | 이어풀기 복원 | 새로고침·재접속 | `nextSeq` 위치로 복원, "이어서 풀기" 배너 |
| 3-7 | 라운드 전환 | 라운드 마지막 문항 제출 | 결과 요약 + 다음 라운드(오답 복습) 이어가기 |
| 3-8 | 모의고사 흐름 | 회차 선택 → 모의고사 → 일부 선택 → 새로고침 → 제출 확인 → 결과 | 미응답 수 유지, 제출 대화상자에 미응답 강조, 결과·해설 재조회 |
| 3-9 | 이력 화면 | 헤더 `이전 결과` → `/history` | 최근 사이클·모의고사 목록, 항목에서 이어풀기/결과 이동, 빈 상태 안내 |
| 3-10 | 키보드만 | Tab·방향키·Enter·Esc | 보기 선택·제출·다음 문항·대화상자 열고 닫기 모두 가능 |
| 3-11 | 반응형 | 375px / 1280px | 가로 넘침·겹침 없음(모바일 헤더 잘림 없음 포함) |
| 3-12 | 백엔드 중지 | 백엔드 내린 상태로 홈/연습 | 오류 안내 문구(uvicorn 기동 안내), 콘솔 예외 없음 |

## 4. 운영 배포 (EC2 · `https://yangyag5.duckdns.org`)

| # | 케이스 | 명령 | 기대 |
|---|---|---|---|
| 4-1 | 헬스 | `curl -s .../api/health` | 200 `database: ok`, `dbUrlSource: EXAM_DB_URL` |
| 4-2 | 홈·SPA 경로 | `curl -sI .../`, `.../exams`, `.../history/` | 200, title `정보처리기사 필기` |
| 4-3 | API·도식 프록시 | `.../api/subject-cycles/overview`, `.../figures/2026-1/099.png` | 200 실데이터 / 200 이미지 |
| 4-4 | HTTP 리다이렉트 | `curl -sI http://yangyag5.duckdns.org/` | 301 → https. 301 은 EC2 호스트 nginx 에 certbot 이 넣은 설정 — 저장소 `deploy/nginx-yangyag5-exam.conf` 는 80 만 열려 있어 **리포 파일만으로는 재현되지 않는다** |
| 4-5 | 인증서 | SSH `sudo certbot certificates` | `yangyag5.duckdns.org` 유효(자동 갱신 등록) |
| 4-6 | 컨테이너 상태 | SSH `cd /home/ubuntu/exam && docker compose ps` | `exam-back` healthy, `exam-front` healthy, 포트 `127.0.0.1:8091` |
| 4-7 | 자동 복구 | SSH `docker restart exam-back` | 30초 내 healthy 복귀, 사이트 정상 |
| 4-8 | 로그 | SSH `docker logs --tail 50 exam-back` | 기동 로그·요청 로그에 예외 없음 |
| 4-9 | DB | SSH `docker exec yangyag-postgres psql -U auto -d exam -c "select count(*) from ipe.question"` | 1,300 (진도 테이블은 사용 상태에 따름) |
| 4-10 | 리소스 | SSH `free -m`, `df -h /`, `docker stats --no-stream` | 메모리 여유·디스크 여유, 컨테이너가 mem_limit 내 |
| 4-11 | 재배포 | 로컬 `./deploy/deploy.sh` | 이미지 load·재기동 후 4-1~4-3 재통과 |
| 4-12 | 롤백 준비 | SSH `docker images \| grep exam-` | 직전 태그 보존 확인(롤백 절차는 `deploy/README.md`) |
| 4-13 | 백엔드 장애 시 화면 | SSH `docker stop exam-back` → 사이트 확인 | 프록시 오류(502) 또는 안내 — 사용자에게 보이는 동작 기록 후 `start` |
| 4-14 | 같은 오리진 확인 | 브라우저 devtools(또는 `curl -H 'Origin: https://yangyag5.duckdns.org'`) | CORS 헤더 불필요(프론트 nginx 프록시 경유) |

## 5. 릴리스 체크리스트 (순서)

1. `tools/validate.py` + `load_db.py --verify`
2. `pytest -q`(198 = 163 + 35, 2026-09-14 기준) — 실패 0
3. `npm ci && npm run build && npm run shots`(2026-09-14 기준 13단계·62컷·exit 0)
4. 스크린샷 육안(홈·연습·모의고사·결과·이력·모바일)
5. 운영 배포: `./deploy/deploy.sh`
6. 운영 검증 표(4-1~4-6) + 재배포 후 재확인
7. 진도 테이블 정리(검증이 만든 행 삭제)
8. 문서 갱신(`back/README.md`·`front/README.md`·`AGENTS.md`) 필요 여부 확인

## 6. 실행 기록 (2026-09-12 · 리비전 `7df9943`)

로컬(Windows + Git Bash, 도커 `postgres` 5432)과 운영(EC2 `43.202.113.123`, `https://yangyag5.duckdns.org`)에서 실제로 돌린 결과.

| 그룹 | 실행 | 결과 |
|---|---|---|
| 1-1~1-3 · 1-5 | `validate` · `--init` ×2 · `--verify` · `report` | **통과** — 65파일/1,300문항 오류 0, 멱등(2회 무오류), 진도 0행 복원, 잔여물 0. `--init` 은 `PYTHONIOENCODING` 없이 실행(= cp949 방어 확인) |
| 1-4 | `build_index` | 통과("이상 없음") + `data/index.json` 되돌림 확인 |
| 1-6 | `dups` | 통과(회차별 신규/중복 리포트) |
| 1-8 | PDF 도구 | **skip** — 실행 당시 pymupdf 미설치(지금은 1.28.2 설치됨이라 실행 가능) |
| 2-1 | `pytest -q` / `-m integration` | **198 passed / 35 passed** (`TEST_DB_URL` = 전용 `app_test` 로 격리) |
| 2-2 · 2-3 | API 계약 · 동시성 | 위 통합 35건에 포함(슬롯·사이클·모의고사·경합 5종) |
| 3-1 · 3-2 | `build` + `shots` | **전 항목 통과 · 57컷**(실행 시점 값 — 현재 기준 13단계·62컷. 실데이터 단언을 API 값에서 유도하도록 고친 뒤) |
| 3-3~3-12 | 화면 흐름·접근성·반응형 | `shots` 자체 점검 + 스크린샷 육안 점검(홈·연습·모의고사·결과·이력·모바일) |
| 4-1~4-6 · 4-8~4-10 · 4-14 | 운영 정상 경로 | 통과 — 헬스 200(DB ok), `/`·`/exams`(301→`/exams/`)·`/history/`·overview·도식 200, 인증서 유효, 컨테이너 healthy, 로그 예외 없음, 리소스 여유 |
| 4-7 | 백엔드 재시작 | 통과 — `docker restart exam-back` 후 12초 내 health 200 |
| 4-11 | 재배포 | 통과 — `./deploy/deploy.sh` 로 이미지 교체·재기동 후 4-1~4-3 재통과 |
| 4-12 | 롤백 태그 | **발견·수정** — 배포가 태그를 덮어써 롤백 지점이 없었다 → `before-<타임스탬프>` 자동 보존으로 고침(`deploy.sh`), 운영에 `before-20260912-1510` 생성 |
| 4-13 | 백엔드 장애 시 | 기록 — SPA 는 200, `/api/health` 직접 호출은 nginx **502/504**(앱 화면은 자체 안내 표시), 복구 후 정상 |
| 5 | 릴리스 체크리스트 | 위 항목으로 실행 완료 |

**이 실행에서 발견해 고친 것**

| 발견 | 조치 |
|---|---|
| 사용자 진행 기록(과목1 사이클 #330) 때문에 통합 테스트 2건 실패 | 통합 테스트를 `TEST_DB_URL`(전용 `app_test`)로 격리 + 기존 기록이 있으면 skip·안내 (`657e090`) |
| 같은 이유로 `npm run shots` 2건 실패 | 실데이터 단언을 overview 응답에서 유도(하드코딩 제거) + 변이 테스트로 검출력 확인 (`7df9943`) |
| 배포 시 롤백 태그가 사라짐 | 직전 이미지를 `before-<타임스탬프>` 로 자동 보존, README 롤백 절차 갱신 (`8e4abf6`) |

**재실행 시 주의**
- 통합 테스트: `.env` 의 `TEST_DB_URL` 이 있으면 그 DB 로 붙는다(없으면 기존 DB — 사용자 데이터가 있으면 사이클 테스트는 skip).
- 프론트 `shots`: 실데이터 값은 API 와 대조하므로 사용자 진행 기록이 있어도 통과한다. 단 백엔드(8092)가 떠 있어야 한다.
- 운영 검증은 `./aws/connect.sh` 와 `curl` 로. 롤백 태그가 쌓이면 오래된 것부터 `docker rmi` 로 정리한다.

## 7. 재실행 검증 (2026-09-12 · 리비전 `d10f905`)

같은 케이스를 다시 처음부터 돌린 2회차 결과. 로컬은 Windows + Git Bash + 도커 `postgres`(5432), 운영은 EC2 `43.202.113.123`(`https://yangyag5.duckdns.org`).

| 그룹 | 실행 | 결과 |
|---|---|---|
| 1-1 · 1-3 · 1-5 | `validate` · `--verify` · `report` | **통과** — 65파일/1,300문항 오류 0, 진도 테이블 "전부 통과", 잔여물 0, 그림 24/24 |
| 1-2 · 1-7 | `--init` ×2, `PYTHONIOENCODING` 없이 `--init` | **통과** — 두 번 모두 rc=0(001~004 적용), cp949 콘솔에서 UnicodeEncodeError 없음 |
| 1-4 | `build_index` | 통과("이상 없음") + `git checkout -- data/index.json` 으로 되돌림 |
| 1-6 | `dups` | 통과 — 1,298문항 / 고유 847(도구 기준) |
| 1-8 | PDF 도구 | **skip** — 실행 당시 `pymupdf` 미설치(지금은 1.28.2 설치됨) |
| 2-1 | `pytest -q` / `-m integration` / `-m "not integration"` | **198 / 35 / 163 passed** (수정 후 18.8초) |
| 2-1-4 | `.env` 없는 사본에서 `pytest -q` | **163 passed / 35 skipped / 78초** — 아래 발견·수정 1 |
| 2-2 · 2-3 | 실서버 HTTP 계약 검증(`app_test` DB · 8093) | **35건 전부 통과** — 슬롯·사이클·모의고사 제출·경합 5종 포함 |
| 3-1 · 3-2 | `npm ci && npm run build` / `npm run shots` | 타입 오류 0 · 빌드 성공 / **모든 점검 통과**(rc=0, 57컷 — **실행 시점 값**, 현재 기준 13단계·62컷) |
| 3-3 | 스크린샷 육안 | 홈·연습(코드·표·도식)·모의고사 그리드·제출 대화상자(미응답 88 강조)·결과·이력·모바일 375px 모두 정상, 오답 자동 펼침/정답 접힘 확인 |
| 4-1~4-6 · 4-8~4-10 · 4-12 · 4-14 | 운영 정상 경로 | 통과 — 헬스 200(DB ok `EXAM_DB_URL`), `/`·`/history/` 200 + title, overview·도식 200, `/exams` 301→`/exams/`, 인증서 VALID 89일 + `certbot.timer`, 컨테이너 healthy, DB 1,300, 롤백 태그 2개 보존 |
| 4-7 | `docker restart exam-back` | 통과 — **3초** 만에 health 200, healthy 복귀 |
| 4-11 | `./deploy/deploy.sh` | 통과 — rc=0, `before-20260912-1702` 태그 보존, 재기동 후 4-1~4-3 재통과 |
| 4-13 | `docker stop exam-back` | 기록 — SPA `/` 는 **200 유지**, `/api/*` 는 즉시 502 가 아니라 nginx 프록시가 `proxy_read_timeout 30s` 동안 대기(직접 curl 은 10초에서 포기). 프론트는 모든 API 호출에 10초 자체 타임아웃(`retry: 0, timeout: 10000`)이 있어 안내 화면으로 넘어간다. `docker start` 후 4초 만에 정상 |
| 5 | 릴리스 체크리스트 | 위 항목으로 실행 완료. 진도 테이블은 검증 전 상태로 복원(로컬 `app` 은 사용자 기록 1사이클/176슬롯 그대로, `app_test` 는 0행) |

**이 실행에서 발견해 고친 것**

| 발견 | 조치 |
|---|---|
| `.env` 없이 돌리면(2-1-4) 통합 테스트가 skip 될 때마다 **약 2분**을 기다렸다 — `localhost` 가 IPv6(`::1`)부터 시도하는데 `psycopg.connect` 에 타임아웃이 없어 죽은 주소마다 OS 기본값을 채웠다. 통합 35건이면 한 시간을 넘겨, 케이스가 사실상 못 쓰는 상태였다 | `back/tests/conftest.py` 에 `PGCONNECT_TIMEOUT=5` 를 걸어(`CONNECT_TIMEOUT_SECONDS`) **163 passed / 35 skipped / 78초** 로 단축. `back/README.md` 테스트 절에 이유·수치 기록 |

**재실행 시 주의(2회차에서 추가)**
- 2-2·2-3 은 `TEST_DB_URL` 의 `app_test` DB 로 서버를 하나 더 띄워 확인하면 사용자 진도와 완전히 분리된다(끝나면 그 DB 의 `study_*` 를 TRUNCATE). 검증 스크립트는 `tmp/`(gitignore)에 두었다.
- 4-13 의 실제 동작은 "502 즉시" 가 아니라 **프록시 대기 → 프론트 자체 타임아웃 → 안내 화면** 이다. 즉시 502 를 원하면 `deploy/front-nginx.conf` 의 `/api/` 에 `proxy_connect_timeout` 을 추가하면 된다(선택).
- `pytest` 는 표준출력을 파일로 넘기면 블록 버퍼링 때문에 진행 상황이 늦게 보인다 — 멈춘 것으로 오해하지 말 것.

## 부록 A. 이 문서가 다루지 않는 것

- **사람이 판단하는 것**: 디자인 선호, 문구 톤, 정보 밀도 → 스크린샷으로 확인
- **부하·보안 테스트**: 단일 사용자 앱이고 별도 인증을 걸지 않았다(운영 정책 결정 필요)
- **PDF 파이프라인**: `pymupdf` 1.28.2 설치됨(없을 때만 `python -m pip install pymupdf`) — `extract.py`·`crop_figures.py`·`scan_figures.py` 로 PDF 재추출·재크롭하는 일은 이 문서의 케이스 범위 밖
- **브라우저 실사용 검증**: 실제 휴대폰·PC 에서의 체감(통신 지연, 터치) → 사용자 확인

## 부록 B. 자주 쓰는 명령 모음

```bash
# 로컬 기동
cd back && ./.venv/Scripts/python -m uvicorn app.main:app --port 8092 &
cd front && npm run dev &                       # http://localhost:8091

# 검증 3종
python tools/validate.py && python tools/load_db.py --verify
cd back && .venv/Scripts/python -m pytest -q
cd front && npm run build && npm run shots

# 운영
./aws/connect.sh "cd /home/ubuntu/exam && docker compose ps"
./deploy/deploy.sh

# 진도 초기화(검증 후)
docker exec postgres psql -U yangyag -d app -c "TRUNCATE ipe.study_session_item, ipe.study_attempt, ipe.study_state, ipe.study_session, ipe.study_cycle RESTART IDENTITY"
```
