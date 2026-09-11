# ipe 스키마 (정보처리기사 필기 기출문제 데이터셋)

`app` 데이터베이스 안에 `ipe` 스키마로 들어갑니다. **소유자와 접속 계정은 기존 앱과 동일한 `yangyag`** 입니다.
기존 `english` / `english_test` 스키마는 건드리지 않습니다.

## 무엇이 들어가나

| 테이블 | 행 수 | 내용 |
|---|---|---|
| `subject` | 5 | 과목 (1~5과목, 각 20문항) |
| `exam` | 13 | 회차. id 형식 `2026-1` |
| `question` | 1,300 | 문항. `doc jsonb` 에 원본 JSON 통째로 보관 |
| `question_choice` | 5,200 | 보기 4개. 정답 여부(`is_correct`)와 보기별 해설(`why`) 포함 |
| `tag` | 1,281 | 복습용 키워드 |
| `question_tag` | 3,347 | 문항–태그 연결 |

그림은 파일로 서빙합니다. DB에는 `question.figure_image` 경로(`figures/2026-1/099.png`, `data/` 기준 상대경로)와 `figure_alt` 만 들어갑니다.

학습 기록(진도) 테이블 3종과 통계 뷰 3종은 아래 **진도 관리** 섹션에 따로 정리했습니다. 지금은 0행입니다(앱이 쓰는 데이터).

## 진도 관리 (db/002_progress.sql)

로그인 없는 단일 사용자 기준의 최소 구조입니다(기존 영어 앱의 `study_session`/`word_result`/`study_state` 와 같은 결). 응시·풀이 기록을 쌓고, 오답 복습 화면이 쓸 상태를 문항당 1행으로 유지합니다.

### 테이블

**`study_session` — 학습/응시 묶음 1건**

| 컬럼 | 의미 |
|---|---|
| `id` | 세션 번호 (serial) |
| `mode` | `exam`(회차 모의고사) · `subject`(과목 연습) · `random`(랜덤 출제) · `review`(오답 복습) |
| `exam_id` | 대상 회차 → `exam.id`. 랜덤·오답 복습처럼 특정 회차가 아니면 NULL |
| `subject_code` | 대상 과목 → `subject.code`. 회차 모의고사처럼 전체 과목이면 NULL |
| `started_at` / `finished_at` | 시작·종료 시각. `finished_at` 이 NULL 이면 진행 중 |

**`study_attempt` — 응답 1건 = 1행 (append-only, 수정하지 않음)**

| 컬럼 | 의미 |
|---|---|
| `id` | 응답 번호 (serial) |
| `session_id` | 어느 세션의 응답인지 → `study_session.id`. 세션 밖 단발 풀이(오답 확인 등)는 NULL |
| `question_id` | 문항 → `question.id` |
| `choice_no` | 사용자가 고른 보기 번호(1~4). 정답 번호는 `question.answer` |
| `is_correct` | 맞았는지 |
| `elapsed_ms` | 응답까지 걸린 시간(ms). 모르면 NULL |
| `answered_at` | 응답 시각 |

**`study_state` — 문항당 1행인 현재 상태 (응답할 때마다 갱신)**

| 컬럼 | 의미 |
|---|---|
| `question_id` | 문항 → `question.id` (기본키) |
| `attempt_count` · `correct_count` · `wrong_count` | 응답·정답·오답 누계. `correct_count + wrong_count = attempt_count` |
| `last_is_correct` · `last_choice_no` · `last_answered_at` | 마지막 응답의 정답 여부·보기 번호·시각 |
| `streak` | 연속 정답 수. 틀리면 0으로 되돌림 |
| `bookmarked` | 북마크 여부 |
| `note` | 오답 메모(자유 입력) |
| `review_due_on` | 복습 예정일. NULL 이면 아직 예약 안 함 |
| `updated_at` | 마지막 갱신 시각 |

원장은 `study_attempt` 이고, 목록·복습 화면은 `study_state` 만 보면 되도록 비정규화해 두었습니다.

### 통계 뷰

| 뷰 | 내용 |
|---|---|
| `v_subject_stats` | 과목별 응답 수·정답·오답·정답률(`accuracy_pct`)·학습한 문항 수(`questions_seen`). 응답 0건 과목도 행이 나오고 `accuracy_pct` 는 NULL |
| `v_wrong_questions` | 한 번이라도 틀린 문항(`wrong_count > 0`). `last_is_correct` 로 미해결 오답만 골라 쓴다 |
| `v_review_due` | `review_due_on` 이 오늘 이하인 문항. `overdue_days` = 밀린 일수(0=오늘) |

### 적용

`db/002_progress.sql` 은 `--init` 에 포함되어 있어 별도 명령이 필요 없습니다. `db/*.sql` 을 파일명 순서로 전부 적용하므로 `001_schema.sql`(문항) 다음에 실행됩니다.

```bash
python tools/load_db.py --init     # db/001_schema.sql → db/002_progress.sql (000_bootstrap.sql 은 제외)
```

psql 로 직접 실행해도 됩니다(재실행 안전).

```bash
docker exec -i postgres psql -U yangyag -d app -f - < db/002_progress.sql
```

되돌리려면 뷰 → 테이블 순서로 지웁니다. 문항 테이블은 그대로 둡니다.

```sql
DROP VIEW  IF EXISTS ipe.v_review_due, ipe.v_wrong_questions, ipe.v_subject_stats;
DROP TABLE IF EXISTS ipe.study_attempt, ipe.study_state, ipe.study_session;
```

### 자주 쓰는 조회

```sql
-- 1) 과목별 정답률 (응답이 없으면 answered=0, accuracy_pct=NULL)
select subject_code, subject_name, answered, correct, accuracy_pct, questions_seen
from ipe.v_subject_stats
order by subject_code;

-- 2) 아직 못 맞춘 오답 문항 (마지막 응답이 틀린 것만)
select question_id, exam_id, number, subject_name, wrong_count, last_answered_at
from ipe.v_wrong_questions
where not last_is_correct
order by last_answered_at desc nulls last, question_id;

-- 3) 오늘까지 복습 예정인 문항
select question_id, exam_id, number, subject_name, review_due_on, overdue_days
from ipe.v_review_due
order by review_due_on, question_id;

-- 4) 북마크한 문항 (상태 테이블 직접 조회)
select question_id, attempt_count, wrong_count, last_is_correct, note
from ipe.study_state
where bookmarked
order by last_answered_at desc nulls last;
```

### 응답 기록 예시 (쓰기)

`study_attempt` 에 원장을 남기고, 같은 트랜잭션에서 `study_state` 를 upsert 합니다. `correct_count + wrong_count = attempt_count` 제약을 유지해야 하므로 증감은 `excluded` 값으로 계산합니다.

```sql
-- 세션 시작. 받은 id 를 아래 session_id 로 쓴다 (mode: exam|subject|random|review)
insert into ipe.study_session (mode, exam_id, subject_code)
values ('exam', '2026-1', null)
returning id;

-- 응답 1건
insert into ipe.study_attempt (session_id, question_id, choice_no, is_correct, elapsed_ms)
values (1, '2026-1-064', 2, true, 4200);

-- 문항당 1행 상태 갱신
insert into ipe.study_state (question_id, attempt_count, correct_count, wrong_count,
                             last_is_correct, last_choice_no, last_answered_at, streak)
values ('2026-1-064', 1, 1, 0, true, 2, now(), 1)
on conflict (question_id) do update set
    attempt_count    = ipe.study_state.attempt_count + 1,
    correct_count    = ipe.study_state.correct_count + excluded.last_is_correct::int,
    wrong_count      = ipe.study_state.wrong_count + (not excluded.last_is_correct)::int,
    last_is_correct  = excluded.last_is_correct,
    last_choice_no   = excluded.last_choice_no,
    last_answered_at = excluded.last_answered_at,
    streak           = case when excluded.last_is_correct
                            then ipe.study_state.streak + 1 else 0 end,
    updated_at       = now();
```

`bookmarked`·`note`·`review_due_on` 은 복습 정책에 따라 앱이 정하는 값이라 위 upsert 에서는 건드리지 않습니다(insert 시 `false`/NULL). 필요하면 같은 트랜잭션에서 따로 갱신합니다.

```sql
update ipe.study_state
set bookmarked = true, note = '헷갈림', review_due_on = current_date + 3
where question_id = '2026-1-064';
```

위 예시(세션 → 응답 → 상태 upsert → 북마크 갱신)와 조회 예시 4개는 실제 DB 에서 실행해 확인했습니다(샘플 기록은 롤백).

## ⚠ search_path 주의

`yangyag` 역할의 `search_path` 는 `english, public` 입니다(기존 영어 앱이 쓰고 있음). **이 역할 전역 설정은 바꾸지 않았습니다** — 바꾸면 기존 앱이 영향을 받습니다.

따라서 `ipe` 테이블을 쓸 때는 다음 중 하나로 접근하세요.

```sql
-- 1) 스키마를 명시
select * from ipe.question;

-- 2) 접속 시 search_path 지정 (앱에서 권장)
--   postgresql://yangyag:***@localhost:5432/app?options=-csearch_path%3Dipe,public
--   또는 접속 직후:  SET search_path = ipe, public;
```

`tools/load_db.py` 는 접속할 때 세션 `search_path` 를 `ipe,public` 으로 고정하므로 역할 설정과 무관하게 동작합니다.

## 실행 순서

### 0) 접속 정보 준비

```bash
cp .env.example .env      # 그리고 EXAM_DB_URL 값에 비밀번호를 채웁니다 (.env 는 git 에 안 들어감)
```

### 1) 스키마·역할 준비 (superuser, 최초 1회)

```bash
# 로컬(docker)
docker exec -i postgres psql -U postgres -d app -f - < db/000_bootstrap.sql

# EC2 등 psql 이 직접 있는 서버
psql -U postgres -d app -f db/000_bootstrap.sql
```

`yangyag` 역할이 없으면 만들고(비밀번호는 실행 후 교체), `ipe` 스키마를 `yangyag` 소유로 만들고, `pg_trgm` 확장을 설치합니다. **이미 있으면 아무것도 바꾸지 않습니다.**

### 2) 테이블 생성 + 데이터 적재

```bash
python tools/load_db.py --init     # db/*.sql 마이그레이션을 파일명 순서로 전부 적용 (000_bootstrap.sql 은 직접 실행)
python tools/load_db.py            # data/questions 전체 적재 + 검증
```

`--init` 은 `db/` 의 SQL 을 파일명 오름차순으로 실행하므로 `001_schema.sql`(문항) → `002_progress.sql`(진도) 순서로 들어갑니다. `000_bootstrap.sql` 은 superuser 권한과 psql 메타명령이 필요해 `--init` 에서 제외되므로 위 1) 단계에서 따로 실행합니다. `db/` 에 SQL 파일을 새로 추가하면 자동으로 포함됩니다.

두 명령 모두 **몇 번을 실행해도 같은 결과**입니다(멱등). JSON에서 사라진 문항은 적재 시 정리됩니다.

### 3) 검증만 다시

```bash
python tools/load_db.py --verify
```

행 수, 정답 분포(JSON 대조), 보기 4개 여부, 정답 1개 여부, 과목 범위, 그림 파일 존재를 확인합니다.

## 접속 문자열

`tools/load_db.py` 는 아래 순서로 접속 대상을 정합니다.

1. `EXAM_DB_URL` (환경변수 또는 저장소 루트 `.env`)
2. `DATABASE_URL`
3. libpq `PG*` 환경변수 (`PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`)
4. 기본값 `postgresql://yangyag@localhost:5432/app` (비밀번호 없음 → `.env` 나 환경변수를 쓰세요)

```bash
# EC2 예시
EXAM_DB_URL='postgresql://yangyag:<비번>@127.0.0.1:5432/app' python tools/load_db.py
```

## 처음부터 다시 만들기 (개발용)

```sql
DROP SCHEMA ipe CASCADE;   -- 데이터만 지움. 역할은 그대로 둔다
```

그 뒤 `000_bootstrap.sql` → `--init` → 적재 순서로 다시 만들면 됩니다.
(실제로 이 순서로 처음부터 재구축해서 검증했습니다.)

`app` 데이터베이스의 다른 스키마(`english`, `english_test`, `public`)에는 영향이 없습니다.

## 전체 파이프라인

```
data/*.pdf                    원본 기출문제
   │  python tools/extract.py          좌표 기반 문항 추출
   ▼
data/raw/<회차>.json          1차 추출 결과
   │  (문항 정리·해설 생성)
   ▼
data/questions/<회차>/<과목>.json    최종 문항 데이터 (git 에 들어감)
   │  python tools/build_index.py      앱 진입점
   ▼
data/index.json
   │  python tools/load_db.py          DB 적재
   ▼
PostgreSQL app.ipe
```

**EC2 에서는 PDF 부터 다시 돌릴 필요가 없습니다.** `data/questions/`, `data/figures/`, `data/index.json` 이 저장소에 있으므로 저장소를 받은 뒤 1) 부트스트랩 → 2) 적재만 하면 됩니다.

## 관련 도구

| 명령 | 설명 |
|---|---|
| `python tools/validate.py` | 문항 JSON 검증 (스키마 + 불변식) |
| `python tools/report.py` | 데이터셋 품질 리포트 |
| `python tools/dups.py` | 회차 간·회차 내 중복 문항 분석 |
| `python tools/build_index.py` | `data/index.json` 재생성 |
| `python tools/crop_figures.py` | 그림 크롭 재생성 |
| `python tools/scan_figures.py` | 그림 있는 문항 탐지 |
