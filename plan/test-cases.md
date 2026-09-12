# 테스트 케이스 (에이전트가 직접 실행하는 것)

작성: 2026-09-12. 목적: **릴리스·재배포 전후에 에이전트가 스스로 돌려 확인할 수 있는 케이스**를 한 곳에 모은다.
사람만 판단할 수 있는 것(디자인 선호·문구 톤)은 스크린샷으로 넘기고, 여기서는 기계적으로 판정 가능한 것만 다룬다.

대상: `tools/`(데이터·도구) · `back/`(API) · `front/`(화면) · `deploy/`(운영) · 운영 사이트

## 0. 사전 준비

| 무엇 | 명령·주소 |
|---|---|
| 백엔드(로컬) | `cd back && ./.venv/Scripts/python -m uvicorn app.main:app --port 8092` |
| 프론트(로컬) | `cd front && npm run dev` → `http://localhost:8091` (CORS 는 `localhost:8091` 만 허용) |
| 로컬 DB | `docker exec -i postgres psql -U yangyag -d app` |
| EC2 DB | `docker exec -i yangyag-postgres psql -U auto -d exam` (SSH: `./aws/connect.sh`) |
| 운영 | `https://yangyag5.duckdns.org` |
| 스크린샷 | `tmp/shots*/` (gitignore) — Playwright 캡처는 `npx playwright screenshot` |

**공통 원칙**
- 검증이 만든 진도 행(`study_*`)은 **끝나고 지워 0행으로 복원**한다. 사용자가 만든 행은 건드리지 않는다.
- 운영 DB 는 공용 컨테이너 안의 `exam` 데이터베이스다 — `TRUNCATE/DROP` 은 진도 테이블에만, 문항 데이터에는 금지.
- 실패를 발견하면 케이스 번호·명령·기대값·실제값을 그대로 기록한다.

## 1. 데이터·도구 (`tools/`)

| # | 케이스 | 명령 | 기대 |
|---|---|---|---|
| 1-1 | 문항 JSON 검증 | `python tools/validate.py` | 65파일 / 1,300문항 / **오류 0** |
| 1-2 | 적재 멱등 | `python tools/load_db.py --init` ×2 | 두 번 모두 exit 0, 오류 없음(000 제외 001~004 적용) |
| 1-3 | 적재 정합 | `python tools/load_db.py --verify` | 전부 통과(exam 13·subject 5·question 1,300·choice 5,200·tag 1,281·trgm 2·그림 24/24) |
| 1-4 | 인덱스 재생성 | `python tools/build_index.py` | "이상 없음" rc=0. **실행 후 `git checkout -- data/index.json`**(generatedAt churn) |
| 1-5 | 품질 리포트 | `python tools/report.py` | 잔여물 0, 분포 출력에 오류 없음 |
| 1-6 | 중복 분석 | `python tools/dups.py` | 고유 문항 수 리포트(도구 기준 847) |
| 1-7 | cp949 방어 | `PYTHONIOENCODING` 없이 `python tools/load_db.py --init 2>&1 \| tail -3` | UnicodeEncodeError 없이 rc=0 (2026-09-12 수정) |
| 1-8 | PDF 도구(선택) | `python -c "import fitz"` 후 `python tools/scan_figures.py` | pymupdf 미설치면 **skip** 으로 표시(설치 시 실행) |

## 2. 백엔드 (`back/`)

### 2-1. 자동 테스트

| # | 명령 | 기대 |
|---|---|---|
| 2-1-1 | `pytest -q` | **198 passed** |
| 2-1-2 | `pytest -q -m integration` | 35 passed(실 PostgreSQL `ipe`) |
| 2-1-3 | `pytest -q -m "not integration"` | 163 passed |
| 2-1-4 | `.env` 없이 `pytest -q` | 통합은 skip, 나머지 통과(접속 정보 부재 처리) |

### 2-2. API 계약 (실서버 호출 또는 TestClient, 만든 행은 삭제)

| # | 케이스 | 호출 | 기대 |
|---|---|---|---|
| 2-2-1 | 헬스 | `GET /api/health` | 200 `{"status":"ok","database":"ok"}` |
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
| 3-2 | 자체 점검·캡처 | `npm run shots` | **모든 점검 통과**: 콘솔 오류 0 · 가로 잘림 0 · 클릭 영역 44px · 키보드 조작 · 409 안내 · 정답 비노출 |
| 3-3 | 스크린샷 육안 | `tmp/shots*/` | 홈 · 연습(코드·표·도식) · 모의고사(그리드·제출 대화상자) · 결과 · 이력 · 오류 4종 · 모바일 375px |
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
| 4-4 | HTTP 리다이렉트 | `curl -sI http://yangyag5.duckdns.org/` | 301 → https |
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
2. `pytest -q`(198) — 실패 0
3. `npm ci && npm run build && npm run shots`
4. 스크린샷 육안(홈·연습·모의고사·결과·이력·모바일)
5. 운영 배포: `./deploy/deploy.sh`
6. 운영 검증 표(4-1~4-6) + 재배포 후 재확인
7. 진도 테이블 정리(검증이 만든 행 삭제)
8. 문서 갱신(`back/README.md`·`front/README.md`·`AGENTS.md`) 필요 여부 확인

## 부록 A. 이 문서가 다루지 않는 것

- **사람이 판단하는 것**: 디자인 선호, 문구 톤, 정보 밀도 → 스크린샷으로 확인
- **부하·보안 테스트**: 단일 사용자 앱이고 별도 인증을 걸지 않았다(운영 정책 결정 필요)
- **PDF 파이프라인**: `pymupdf` 미설치 환경에서는 `extract.py`·`crop_figures.py`·`scan_figures.py` 실행 불가 → 설치 후 별도 확인
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
