# ipe 스키마 (정보처리기사 필기 기출문제 데이터셋)

`ipe` 스키마는 데이터베이스 하나 안에 들어갑니다. **로컬은 `app` DB(도커 컨테이너 `postgres`), 운영(EC2)은 공용 컨테이너 `yangyag-postgres` 의 `exam` DB** 이고, **소유자와 접속 계정은 두 환경 모두 기존 앱과 동일한 `yangyag`** 입니다. **운영 DB 스키마 변경·최초 구축은 덤프 복원(`deploy/README.md` §1)이 표준**이고, DDL(`db/*.sql`)과 `tools/load_db.py --init` 은 로컬·신규 구축 경로입니다.
로컬 `app` DB 의 기존 `english` / `english_test` 스키마는 건드리지 않습니다.

**설치 3단계** — ① 부트스트랩(superuser, 최초 1회) → ② `--init`(마이그레이션) → ③ 적재 + 검증. `--init` 은 마이그레이션만 하고 적재하지는 않습니다.

```bash
docker exec -i postgres psql -U postgres -d app -f - < db/000_bootstrap.sql   # 1) 역할·ipe 스키마·pg_trgm (superuser, 최초 1회)
python tools/load_db.py --init                                               # 2) db/*.sql 마이그레이션 (적재는 하지 않음)
python tools/load_db.py                                                      # 3) 문항 적재 + 검증 (검증만 하려면 --verify)
```

운영(EC2) DB 스키마 변경·최초 구축은 이 경로 대신 **덤프 복원(`deploy/README.md` §1)이 표준**입니다. 자세한 절차는 아래 **실행 순서**.

## 목차

- [무엇이 들어가나](#무엇이-들어가나)
- [진도 관리 — 테이블 5종·뷰 3종·mode 5종·주요 제약·경고 1·2](#진도-관리-db002_progresssql--db003_study_itemssql--db004_session_commentssql)
- [⚠ search_path 주의](#-search_path-주의)
- [실행 순서](#실행-순서) — 0) 접속 정보 → 1) 부트스트랩 → 2) 마이그레이션 + 적재 → 3) 검증만
- [접속 문자열](#접속-문자열)
- [처음부터 다시 만들기 (개발용)](#처음부터-다시-만들기-개발용)
- [전체 파이프라인](#전체-파이프라인)
- [관련 도구](#관련-도구)

## 무엇이 들어가나

| 테이블 | 행 수 | 내용 |
|---|---|---|
| `subject` | 5 | 과목 (1~5과목, 각 20문항) |
| `exam` | 13 | 회차. id 형식 `2026-1` |
| `question` | 1,300 | 문항. `doc jsonb` 에 원본 JSON 통째로 보관 |
| `question_choice` | 5,200 | 보기 4개. 정답 여부(`is_correct`)와 보기별 해설(`why`) 포함 |
| `tag` | 1,281 | 복습용 키워드 |
| `question_tag` | 3,347 | 문항–태그 연결 |

그림은 파일로 서빙합니다. **그림 바이너리는 DB에 없고** `question.figure_image`(경로 — `figures/2026-1/099.png`, `data/` 기준 상대경로)·`figure_alt`·`figure_page`·`figure_col`·`figure_box`(좌표)만 둡니다(`db/001_schema.sql`).

학습 기록(진도) 테이블 5종(`study_session`·`study_cycle`·`study_session_item`·`study_attempt`·`study_state`)과 통계 뷰 3종은 아래 **진도 관리** 섹션에 따로 정리했습니다. 보통 0행에서 시작합니다(앱이 쓰는 데이터).

## 진도 관리 (db/002_progress.sql · db/003_study_items.sql · db/004_session_comments.sql)

로그인 없는 단일 사용자 기준의 최소 구조입니다(기존 영어 앱의 `study_session`/`word_result`/`study_state` 와 같은 결). 응시·풀이 기록을 쌓고, 오답 복습 화면이 쓸 상태를 문항당 1행으로 유지합니다.

`003_study_items.sql` 이 **세션의 고정 문항 목록(답안 슬롯)** 과 **과목 학습 사이클** 을 더합니다. 풀이 방식 세 가지(과목 사이클·회차 연습·모의고사)가 모두 "문항 목록을 가진 세션"으로 표현되고, 과목 사이클은 그런 세션의 연쇄(라운드)입니다. **구조·의미의 정본은 `db/003_study_items.sql` 주석**입니다 — 이 문서의 표와 `back/README.md` 의 mode 표는 그 요약입니다.

`004_session_comments.sql` 은 구조를 바꾸지 않고 `study_session` 의 테이블·컬럼 COMMENT 만 다시 찍습니다. `002_progress.sql` 이 옛 4모드(`exam`·`subject`·`random`·`review`) 기준으로 찍어 둔 의미를 지금의 **mode 5종** 에 맞추고, 코멘트가 없던 `mode` 컬럼에 처음 붙입니다(`exam_id`·`subject_code`·`end_reason` 도 함께 다시 찍습니다). `003` 이 찍은 `cycle_id`·`round_no` 와 `study_cycle`·`study_session_item` 코멘트는 그대로 두며, `COMMENT` 는 값을 덮어쓸 뿐이라 **몇 번 실행해도 결과가 같습니다**(멱등).

### 테이블

**`study_session` — 학습/응시 묶음 1건**

| 컬럼 | 의미 |
|---|---|
| `id` | 세션 번호 (serial) |
| `mode` | `subject`(과목 사이클 라운드 1) · `review`(사이클 라운드 2+, 직전 오답 복습) · `exam_practice`(회차별 연습) · `exam`(회차 모의고사) · `random`(랜덤 출제) — 아래 **mode 5종** |
| `exam_id` | 대상 회차 → `exam.id`. 회차 연습·모의고사는 라우터가 반드시 채우고, `random` 은 요청에 `examId` 가 있으면 **그대로 저장**한다(슬롯이 없어 출제에는 영향 없음). 사이클 라운드(`subject`·`review`)는 NULL |
| `subject_code` | 대상 과목 → `subject.code`. 사이클 라운드는 사이클의 과목이, `random` 은 요청한 `subjectCode` 가 그대로 저장된다. 회차 연습·모의고사는 요청에 있어도 저장하지 않는다(NULL) |
| `cycle_id` | 사이클 라운드면 그 사이클 → `study_cycle.id`. 회차 연습·모의고사·랜덤은 NULL |
| `round_no` | 사이클 안의 라운드 번호. `cycle_id` 가 NULL 이면 NULL |
| `end_reason` | 종료 사유 `finished`(정상 종료)·`abandoned`(중단). 진행 중이면 NULL |
| `started_at` / `finished_at` | 시작·종료 시각. `finished_at` 이 NULL 이면 진행 중 |

mode 별로 어떤 값이 들어가는지(API 가 만드는 세션 기준):

| mode | `exam_id` | `subject_code` | `cycle_id`·`round_no` |
|---|---|---|---|
| `subject` | NULL | 사이클의 과목 | 값 있음(`round_no=1`) |
| `review` | NULL | 사이클의 과목 | 값 있음(`round_no>=2`) |
| `exam_practice` | 회차(필수) | NULL(요청에 있어도 저장 안 함) | NULL |
| `exam` | 회차(필수) | NULL(요청에 있어도 저장 안 함) | NULL |
| `random` | 요청값(보통 NULL) | 요청값(보통 NULL) | NULL |

`end_reason` 은 정상 종료면 `finished`, 새로 구성(`replaceActive`)으로 밀려나면 `abandoned` 이고 진행 중이면 NULL 이다. `finished` 는 연습(`subject`·`review`·`exam_practice`)이 마지막 문항 채점으로, 모의고사(`exam`)가 `POST /api/sessions/{id}/submit`(최종 일괄 채점)으로, `random` 이 `/finish` 로 생긴다. 중단된 모의고사(`abandoned`)는 제출할 수 없다(409).

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
| `review_due_on` | 복습 예정일(달력 날짜). NULL 이면 아직 예약 안 함. 복습 대상 판정은 한국 날짜(Asia/Seoul) 기준 |
| `updated_at` | 마지막 갱신 시각 |

원장은 `study_attempt` 이고, 목록·복습 화면은 `study_state` 만 보면 되도록 비정규화해 두었습니다.

**`study_cycle` — 과목 학습 사이클 1건 (db/003_study_items.sql)**

| 컬럼 | 의미 |
|---|---|
| `id` | 사이클 번호 (serial) |
| `subject_code` | 과목 → `subject.code` |
| `status` | `active`(진행 중) · `completed`(어떤 라운드가 오답 없이 끝남) · `abandoned`(진행 중에 새로 구성해 중단) |
| `created_at` / `ended_at` | 시작·종료 시각. `active` 이면 `ended_at` 은 NULL (`study_cycle_ended_chk` 가 강제) |

**`study_session_item` — 세션의 고정 문항 목록 겸 답안 슬롯(문항당 1행) (db/003_study_items.sql)**

| 컬럼 | 의미 |
|---|---|
| `session_id` | 세션 → `study_session.id` (복합 기본키 1/2, `ON DELETE CASCADE`) |
| `seq` | 목록에서의 순서(1부터). 복합 기본키 2/2. 다음에 풀 문항은 아직 안 푼 가장 작은 `seq` |
| `question_id` | 문항 → `question.id`. 한 세션에 같은 문항은 1개뿐(`study_session_item_question_uk`) |
| `choice_no` | 연습: 제출한 보기(채점 후 불변). 모의고사: 현재 고른 보기(NULL = 미응답, 제출 전 수정 가능) |
| `is_correct` | 연습: 제출 즉시 채움(채점 후 불변). 모의고사: 최종 제출 때 채움. NULL 이면 아직 안 풂 |
| `answered_at` | 연습: 제출 시각. 모의고사: 마지막으로 선택을 저장한 시각. `choice_no` 가 있으면 반드시 값이 있음(`study_session_item_answered_chk`) |

목록은 만든 뒤 바뀌지 않고, 진행 위치를 담는 컬럼은 따로 두지 않습니다(슬롯에서 계산). 재적재로 문항이 사라지면 슬롯도 연쇄 삭제되어 `seq` 에 빈 번호가 생길 수 있으므로, 진행도는 행 수로 계산하고 연속 번호를 가정하지 않습니다.

### mode 5종 (`study_session_mode_chk`)

| mode | 쓰임 | 슬롯(`study_session_item`) | 채점 시점 |
|---|---|---|---|
| `subject` | 과목 사이클 라운드 1 — 과목 전체 풀이 | 과목 문항을 내용 기준 중복 제거·셔플한 목록 | 문항별 즉시 |
| `review` | 과목 사이클 라운드 2+ — 직전 라운드 오답 복습 | 직전 라운드에서 `is_correct IS FALSE` 인 문항만 다시 섞은 목록 | 문항별 즉시 |
| `exam_practice` | 회차별 연습 | 회차 문항 번호 순 | 문항별 즉시 |
| `exam` | 회차 모의고사 | 회차 문항 번호 순 | 제출 전에는 선택만 슬롯에 저장(채점 안 함). `POST /api/sessions/{id}/submit` 이 한 트랜잭션에서 일괄 채점하고 세션을 `finished` 로 끝낸다(미응답 문항은 0점 처리, 중단된 모의고사는 409) |
| `random` | 랜덤 출제(슬롯 도입 전부터 있던 기존 기능) | 없음 | 기존 `POST /api/questions/{id}/answer` — 호출마다 `study_attempt` 1행 |

### 라운드와 사이클 흐름

`study_cycle` 은 과목 하나의 학습 연쇄이고, 라운드 1회가 `study_session` 1행입니다. 과목당 진행 중(`active`) 사이클은 1개입니다(`study_cycle_active_uk`).

1. **라운드 1** (`mode='subject'`, `round_no=1`): 과목 문항 260개를 API 의 내용 키(`content_key`)로 묶어 그룹 대표(가장 최근 회차 = id 최대)를 모으고, 섞어서 슬롯 `seq` 1..N 으로 저장합니다(과목별 176~199개).
2. **라운드 2+** (`mode='review'`, `round_no>=2`): 직전 라운드의 오답 문항만 다시 섞습니다.
3. **전환·완료는 마지막 슬롯 채점과 같은 트랜잭션**: 아직 안 푼 슬롯이 없어지면 라운드를 닫고(`finished_at`·`end_reason='finished'`) — 오답이 있으면 다음 라운드 세션을 만들고, 없으면 사이클을 `completed`(`ended_at`)로 바꿉니다. 열린 라운드 1개 인덱스(`study_session_cycle_open_uk`) 때문에 현재 라운드를 먼저 닫은 뒤 다음 라운드를 넣습니다. 그래서 "라운드가 끝났는데 다음 라운드가 없는" 중간 상태가 남지 않습니다.
4. **중단(`abandoned`)**: 진행 중인 사이클에서 새로 구성하면 그 시점에 보이는 열린 라운드 세션과 사이클을 `end_reason='abandoned'`·`status='abandoned'` 로 닫습니다. 중단된 세션에는 더 기록할 수 없습니다.
5. `cycle_id`·`round_no` 는 사이클 라운드만 가집니다(`study_session_round_chk`): `subject` 는 `round_no=1`, `review` 는 `round_no>=2`, `cycle_id` 가 NULL 이면 `round_no` 도 NULL.

`finished_at` 은 계속 "더 이상 기록을 받지 않음"이고, `end_reason` 이 정상 종료(`finished`)와 중단(`abandoned`)을 가릅니다. `study_session_end_reason_chk` 가 둘을 동치로 묶어(`finished_at IS NULL` = `end_reason IS NULL`) 한쪽만 채우는 것을 막습니다.

### 주요 제약·인덱스 (db/003_study_items.sql)

| 이름 | 종류 | 뜻 |
|---|---|---|
| `study_cycle_active_uk` | 유니크 인덱스 (`subject_code`) WHERE `status='active'` | 과목당 진행 중 사이클 1개. 동시 시작 경합은 이 위반으로 API 가 409 를 돌려준다 |
| `study_session_cycle_round_uk` | 유니크 인덱스 (`cycle_id`, `round_no`) WHERE `cycle_id IS NOT NULL` | 사이클 안에서 라운드 번호는 중복될 수 없다 |
| `study_session_cycle_open_uk` | 유니크 인덱스 (`cycle_id`) WHERE `cycle_id IS NOT NULL AND finished_at IS NULL` | 사이클당 열린 라운드는 1개 |
| `study_session_exam_open_uk` | 유니크 인덱스 (`mode`, `exam_id`) WHERE `mode IN ('exam_practice','exam') AND finished_at IS NULL` | (모드, 회차)마다 진행 중 세션 1개 |
| `study_session_item_question_uk` | 유니크 제약 (`session_id`, `question_id`) | 한 세션에 같은 문항은 슬롯 1개 — 재전송 멱등의 근거 |
| `study_session_item_question_idx` | 인덱스 (`question_id`) | 문항별 슬롯 조회·연쇄 삭제용 |

### ⚠ 1) 기존 DB에 이 마이그레이션을 적용하기 전 — 중복 열린 세션 정리

`study_session_exam_open_uk` 는 **값이 있는 DB에 같은 `(mode, exam_id)` 로 열린 세션(`finished_at IS NULL`)이 2개 이상 있으면 생성에 실패**합니다. `tools/load_db.py --init` 은 `db/*.sql` 을 파일마다 커밋하지 않고 **전체를 한 트랜잭션으로 실행한 뒤 마지막에 한 번 커밋**하므로, 이 인덱스 생성이 실패하면 그 실행에서 만들려던 변경(새 테이블·컬럼·다른 인덱스)이 **전부 롤백**됩니다.

기록이 있는 운영 DB에 처음 적용할 때는 먼저 아래 조회로 중복 열린 세션을 찾아 정리(`finished_at`·`end_reason` 채우기 등)한 뒤 `--init` 을 돌리세요. **현재 dev DB 와 새로 구축한 EC2(진도 0행)는 영향이 없습니다.**

```sql
-- 같은 (mode, exam_id) 로 열린 세션이 2개 이상인지
select mode, exam_id, count(*)
from ipe.study_session
where mode in ('exam_practice', 'exam') and finished_at is null
group by mode, exam_id
having count(*) > 1;
```

### ⚠ 2) 'abandoned 사이클 = 열린 세션 없음' 을 가정하면 안 된다

진행 중 사이클을 `replaceActive=true` 로 새로 구성할 때, 열린 라운드 세션을 잠그는 사이에 다른 요청이 마지막 슬롯을 채점해 **새 라운드(review)** 를 커밋하면 그 라운드는 중단된 사이클에 `finished_at IS NULL` 로 남을 수 있습니다(그 창을 잠금 순서를 뒤집어 없애려 하면 `advance_round_if_complete` 와 ABBA 데드락이 나므로 그대로 둔다 — 잠금 순서는 세션 → 슬롯 → 사이클이고, 이 경합 계약은 `back/app/cycles.py` 의 `replace_active_cycle` docstring("경합 시 남는 열린 라운드(계약)")에 정리돼 있다). 데이터 손상은 아니고, 남은 라운드의 마지막 슬롯을 채점하면 라운드만 닫히고 새 라운드는 만들어지지 않아 스스로 회복합니다.

따라서 **홈·사이클 조회·집계는 `status='active'` 사이클만 근거로 삼습니다.** 중단된 사이클에 남은 열린 세션을 세션·슬롯 API 로 계속 푸는 것 자체는 가능하지만(마지막 슬롯 채점이 회복 경로), 그 세션을 '진행 중인 사이클의 라운드' 로 해석하면 안 됩니다.

### 통계 뷰

| 뷰 | 내용 |
|---|---|
| `v_subject_stats` | 과목별 응답 수·정답·오답·정답률(`accuracy_pct`)·학습한 문항 수(`questions_seen`). 응답 0건 과목도 행이 나오고 `accuracy_pct` 는 NULL |
| `v_wrong_questions` | 한 번이라도 틀린 문항(`wrong_count > 0`). `last_is_correct` 로 미해결 오답만 골라 쓴다 |
| `v_review_due` | `review_due_on` 이 오늘(한국 날짜 Asia/Seoul) 이하인 문항. `overdue_days` = 밀린 일수(0=오늘, 클수록 밀림). DB 세션 TimeZone 과 무관하게 Asia/Seoul 날짜로 판정·계산 |

세 뷰는 모두 **전체 기간 누계**(`study_state`·`study_attempt`) 기준이라 사이클·라운드와 무관합니다. 이번 사이클의 오답만 보려면 `study_session_item` 을 쓰세요(아래 7번 조회).

### 적용

`db/002_progress.sql`·`db/003_study_items.sql`·`db/004_session_comments.sql` 은 `--init` 에 포함되어 있어 별도 명령이 필요 없습니다. `db/*.sql` 을 파일명 순서로 전부 적용하므로 `001_schema.sql`(문항) → `002_progress.sql`(진도) → `003_study_items.sql`(슬롯·사이클) → `004_session_comments.sql`(COMMENT 재기록) 순서로 실행됩니다.

```bash
python tools/load_db.py --init     # db/001 → 002 → 003 → 004 (000_bootstrap.sql 은 제외)
```

`--init` 은 **파일마다 커밋하지 않고 전체를 한 트랜잭션**으로 실행하므로, 중간에 실패하면 앞서 적용된 파일까지 함께 롤백됩니다(위 경고 1). psql 로 직접 실행해도 됩니다(재실행 안전).

```bash
docker exec -i postgres psql -U yangyag -d app -f - < db/002_progress.sql
docker exec -i postgres psql -U yangyag -d app -f - < db/003_study_items.sql
docker exec -i postgres psql -U yangyag -d app -f - < db/004_session_comments.sql
```

운영(EC2)에 적용할 때는 컨테이너·DB 이름만 다릅니다(공용 컨테이너 `yangyag-postgres`·`exam` DB). 운영 DB 스키마 변경·최초 구축은 `--init` 대신 **덤프 복원(`deploy/README.md` §1)이 표준**입니다.

되돌리려면 뷰 → 테이블 순서로 지웁니다. 문항 테이블은 그대로 둡니다. `study_cycle` 은 `study_session.cycle_id` 외래 키(`study_session_cycle_id_fkey`)가 가리키므로 **`cycle_id` 컬럼을 지운 뒤에** 떼어내야 합니다(`db/003_study_items.sql` 첫머리 주석과 같은 순서).

```sql
DROP VIEW  IF EXISTS ipe.v_review_due, ipe.v_wrong_questions, ipe.v_subject_stats;
DROP TABLE IF EXISTS ipe.study_session_item;                    -- 003. 답안 슬롯
DELETE FROM ipe.study_session;                                  -- 003 의 CHECK·컬럼을 남기고 행만 비울 때
ALTER TABLE ipe.study_session
    DROP CONSTRAINT IF EXISTS study_session_end_reason_chk,
    DROP CONSTRAINT IF EXISTS study_session_round_chk,
    DROP CONSTRAINT IF EXISTS study_session_mode_chk,
    DROP COLUMN IF EXISTS end_reason,
    DROP COLUMN IF EXISTS round_no,
    DROP COLUMN IF EXISTS cycle_id;
-- mode CHECK 는 002 정의로 다시 만든다 (ADD CONSTRAINT 에는 IF NOT EXISTS 가 없다)
ALTER TABLE ipe.study_session
    ADD CONSTRAINT study_session_mode_chk
    CHECK (mode IN ('exam', 'subject', 'random', 'review'));
DROP TABLE IF EXISTS ipe.study_cycle;                           -- 003. cycle_id 를 지운 뒤에만 삭제된다
DROP TABLE IF EXISTS ipe.study_attempt, ipe.study_state, ipe.study_session;
```

`study_session` 을 003 이전 상태로 되돌리려면 위 `DELETE`·`ALTER` 를 먼저 하고 마지막 줄로 테이블까지 지우면 됩니다(`db/003_study_items.sql` 첫머리 주석과 같은 순서).

`004_session_comments.sql` 은 COMMENT 만 다시 찍으므로, 코멘트를 004 이전 상태로 되돌리려면 아래를 실행합니다. 테이블·`exam_id`·`subject_code` 는 `db/002_progress.sql`(22~24행) 값으로 돌아가고, `end_reason` 은 004 이전 값이 `002` 가 아니라 `db/003_study_items.sql`(65행)에 있으니 그 문구를 다시 찍으며, `mode` 코멘트는 004 가 처음 붙였으니 지웁니다.

```sql
COMMENT ON TABLE ipe.study_session IS '학습/응시 묶음 1건. mode: exam(회차 모의고사)·subject(과목 연습)·random(랜덤)·review(오답 복습)';
COMMENT ON COLUMN ipe.study_session.exam_id IS '대상 회차. 랜덤·오답 복습처럼 특정 회차가 아니면 NULL';
COMMENT ON COLUMN ipe.study_session.subject_code IS '대상 과목. 회차 모의고사처럼 전체 과목이면 NULL';
COMMENT ON COLUMN ipe.study_session.mode IS NULL;                  -- 004 가 최초로 붙인 코멘트를 지운다
COMMENT ON COLUMN ipe.study_session.end_reason IS '종료 사유. finished(정상 종료)·abandoned(중단). 진행 중이면 NULL';
```

다시 004 상태로 돌리려면 `python tools/load_db.py --init`(또는 `db/004_session_comments.sql` 실행)을 씁니다.

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

-- 3) 오늘까지 복습 예정인 문항 (오늘 = 한국 날짜, Asia/Seoul. overdue_days 0=오늘, 1=어제)
select question_id, exam_id, number, subject_name, review_due_on, overdue_days
from ipe.v_review_due
order by review_due_on, question_id;

-- 4) 북마크한 문항 (상태 테이블 직접 조회)
select question_id, attempt_count, wrong_count, last_is_correct, note
from ipe.study_state
where bookmarked
order by last_answered_at desc nulls last;

-- 5) 과목별 진행 중 사이클과 라운드 현황 (홈 화면용. active 사이클만 본다 — 위 경고 2)
select c.subject_code, c.status, s.round_no, s.mode, s.end_reason,
       count(i.*) as item_count,
       count(i.choice_no) as answered,
       count(*) filter (where i.is_correct) as correct
from ipe.study_cycle c
left join ipe.study_session s on s.cycle_id = c.id
left join ipe.study_session_item i on i.session_id = s.id
where c.status = 'active'
group by c.subject_code, c.status, s.round_no, s.mode, s.end_reason
order by c.subject_code, s.round_no;

-- 6) 이어풀기 위치: 아직 안 푼 가장 작은 seq (모의고사는 is_correct 대신 choice_no is null)
select min(seq) as next_seq
from ipe.study_session_item
where session_id = 1 and is_correct is null;

-- 7) 이번 사이클·라운드의 오답 문항 (다음 라운드 구성과 같은 기준)
select i.seq, i.question_id
from ipe.study_session_item i
where i.session_id = 1 and i.is_correct is false
order by i.seq;
```

### 응답 기록 예시 (쓰기)

`study_attempt` 에 원장을 남기고, 같은 트랜잭션에서 `study_state` 를 upsert 합니다. `correct_count + wrong_count = attempt_count` 제약을 유지해야 하므로 증감은 `excluded` 값으로 계산합니다.

```sql
-- 세션 시작. 받은 id 를 아래 session_id 로 쓴다 (mode: subject|review|exam_practice|exam|random)
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

`bookmarked`·`note`·`review_due_on` 은 복습 정책에 따라 앱이 정하는 값이라 위 upsert 에서는 건드리지 않습니다(insert 시 `false`/NULL). 필요하면 같은 트랜잭션에서 따로 갱신합니다. 복습 예정일은 뷰와 같은 한국 날짜(Asia/Seoul) 기준으로 넣습니다 — 세션 TimeZone(`Etc/UTC` 등)에 따라 `current_date` 가 달라지므로 그 대신 아래 식을 씁니다.

```sql
update ipe.study_state
set bookmarked = true, note = '헷갈림',
    review_due_on = (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')::date + 3
where question_id = '2026-1-064';
```

위 예시(세션 → 응답 → 상태 upsert → 북마크 갱신)와 조회 예시 1~4번은 실제 DB 에서 실행해 확인했습니다(샘플 기록은 롤백).

사이클 라운드 세션과 슬롯은 **한 트랜잭션**에서 만듭니다(API `POST /api/subject-cycles`·`POST /api/sessions` 가 하는 일과 같음).

```sql
begin;
-- 1) 사이클 (진행 중 사이클이 있으면 study_cycle_active_uk 위반 → API 는 409)
insert into ipe.study_cycle (subject_code) values (1) returning id;          -- 예: 7

-- 2) 라운드 1 세션. cycle_id·round_no 는 함께 넣어야 study_session_round_chk 를 통과한다
insert into ipe.study_session (mode, subject_code, cycle_id, round_no)
values ('subject', 1, 7, 1) returning id;                                    -- 예: 12

-- 3) 슬롯 목록 (연습: seq 1..N, 아직 안 푼 상태 = is_correct NULL)
insert into ipe.study_session_item (session_id, seq, question_id)
values (12, 1, '2026-1-001'), (12, 2, '2025-3-004');

-- 4) 연습 슬롯 채점: 원장 1행 + 누계 upsert + 슬롯에 결과 기록을 같은 트랜잭션에서
insert into ipe.study_attempt (session_id, question_id, choice_no, is_correct)
values (12, '2026-1-001', 3, false);
update ipe.study_session_item
set choice_no = 3, is_correct = false, answered_at = now()
where session_id = 12 and seq = 1;
-- (마지막 슬롯이면 같은 트랜잭션에서 라운드 종료 → 오답 라운드 생성 또는 사이클 completed)
commit;
```

`UPDATE study_session SET finished_at` 을 직접 쓸 때는 `end_reason` 도 함께 채워야 합니다(`study_session_end_reason_chk`). 슬롯 세션은 API 경로(`PUT /api/sessions/{id}/items/{seq}/answer`)가 이 전환을 대신 처리합니다.

## ⚠ search_path 주의

`yangyag` 는 로컬 `app` DB 에서 `search_path=english, public` 로 돕니다(기존 영어 앱이 쓰고 있음). 역할 속성에는 값이 없고 `ALTER ROLE yangyag IN DATABASE app SET search_path ...` 로 **DB 하나에만** 걸려 있습니다 — 이 설정을 바꾸면 기존 앱이 영향을 받습니다.

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
# 로컬(docker) — 컨테이너 postgres 의 app DB
docker exec -i postgres psql -U postgres -d app -f - < db/000_bootstrap.sql

# psql 이 직접 있고 데이터베이스 이름이 app 인 서버
psql -U postgres -d app -f db/000_bootstrap.sql
```

`yangyag` 역할이 없으면 만들고(비밀번호는 실행 후 교체), `ipe` 스키마를 `yangyag` 소유로 만들고, `pg_trgm` 확장을 설치합니다. **이미 있으면 아무것도 바꾸지 않습니다.**

운영(EC2)은 컨테이너·DB 이름이 다릅니다 — 공용 컨테이너 `yangyag-postgres` 의 `exam` DB 입니다. **운영 DB 스키마 변경·최초 구축은 덤프 복원(`deploy/README.md` §1)이 표준**이고, 이 1) 단계(부트스트랩)와 2) 단계의 `--init` 은 로컬·신규 구축 경로입니다. `db/000_bootstrap.sql` 에는 `GRANT CONNECT ON DATABASE app` 처럼 DB 이름이 박힌 줄이 있으니, 대상 DB 이름이 다르면 그 줄을 맞춰 실행하세요(`exam` DB 에 그대로 쓰면 실패).

### 2) 테이블 생성 + 데이터 적재

```bash
python tools/load_db.py --init     # db/*.sql 마이그레이션을 파일명 순서로 전부 적용 (000_bootstrap.sql 은 직접 실행)
python tools/load_db.py            # data/questions 전체 적재 + 검증
```

`--init` 은 `db/` 의 SQL 을 파일명 오름차순으로 실행하므로 `001_schema.sql`(문항) → `002_progress.sql`(진도) → `003_study_items.sql`(슬롯·사이클) → `004_session_comments.sql`(COMMENT 재기록) 순서로 들어갑니다. `000_bootstrap.sql` 은 superuser 권한과 psql 메타명령이 필요해 `--init` 에서 제외되므로 위 1) 단계에서 따로 실행합니다. `db/` 에 SQL 파일을 새로 추가하면 자동으로 포함됩니다.

**`--init` 은 전체를 한 트랜잭션으로 실행합니다.** 어느 파일에서든 실패하면 그 실행의 변경이 전부 롤백되므로(예: 기존 DB의 중복 열린 세션 때문에 `study_session_exam_open_uk` 생성 실패 — 위 경고 1), 기존 DB에 처음 적용할 때는 먼저 진도 테이블 상태를 확인하세요.

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

운영(EC2)의 `EXAM_DB_URL` 은 공용 컨테이너 `yangyag-postgres` 의 `exam` DB 를 가리킵니다 — 접속 문자열(계정·비밀번호)은 EC2 의 `/home/ubuntu/exam/.env` 에만 두고 `deploy/README.md` 절차로 넣습니다. 로컬에서 확인만 할 때는 아래처럼 실행합니다.

```bash
python tools/load_db.py --verify   # 저장소 루트 .env 의 EXAM_DB_URL 을 쓴다
```

## 처음부터 다시 만들기 (개발용)

```sql
DROP SCHEMA ipe CASCADE;   -- 데이터만 지움. 역할은 그대로 둔다
```

그 뒤 `000_bootstrap.sql` → `--init` → 적재 순서로 다시 만들면 됩니다.
(실제로 이 순서로 처음부터 재구축해서 검증했습니다.)

로컬 `app` 데이터베이스의 다른 스키마(`english`, `english_test`, `public`)에는 영향이 없습니다.

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
PostgreSQL `ipe` (로컬 `app` DB · 운영 EC2 `exam` DB)
```

**EC2 에서는 PDF 부터 다시 돌릴 필요가 없습니다.** `data/questions/`, `data/figures/`, `data/index.json` 이 저장소에 있으므로 저장소를 받은 뒤 적재(`python tools/load_db.py`)만 하면 됩니다. 운영 DB 스키마 변경·최초 구축은 덤프 복원(`deploy/README.md` §1)이 표준이고, `tools/load_db.py --init` 은 로컬·신규 구축 경로입니다.

## 관련 도구

| 명령 | 설명 |
|---|---|
| `python tools/validate.py` | 문항 JSON 검증 (스키마 + 불변식) |
| `python tools/report.py` | 데이터셋 품질 리포트 |
| `python tools/dups.py` | 회차 간·회차 내 중복 문항 분석 |
| `python tools/build_index.py` | `data/index.json` 재생성 |
| `python tools/crop_figures.py` | 그림 크롭 재생성 |
| `python tools/scan_figures.py` | 그림 있는 문항 탐지 |
