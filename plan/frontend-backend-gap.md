# 프론트 설계서 대비 백엔드·DB 보완 설계

상태: 초안 — `plan/frontend-design.md`(대화로 보완 중인 초안)에 맞춰 함께 갱신한다  
작성일: 2026-09-11  
기준 커밋: `6adb2de`

이 문서는 프론트 설계서의 흐름을 현재 백엔드 API·DB로 구현할 수 있는지 판단하고, 부족한 부분의 DB·API 설계를 제안한다. 백엔드 코드·DDL·데이터는 수정하지 않았다.

## 1. 결론

**현재 백엔드로는 설계서의 핵심 흐름을 구현할 수 없다.** 문항 표시와 문항별 즉시 채점·해설은 지금 API로 충분하다. 그러나 설계서가 확정한 풀이 방식들은 공통으로 다음을 전제한다: 구성한 문제 목록을 서버에 고정해 두고, 문항마다 답안을 한 번씩만 기록하며, 중단한 위치에서 이어갈 수 있어야 한다. 현재 DB에는 이 정보를 담을 구조가 없다.

| 영역 | 판정 | 요지 |
|---|---|---|
| 문제·보기·지문·도식 표시, 문항별 채점·해설 | 가능 | 기존 조회 API와 채점 응답을 그대로 사용 |
| 과목별 학습 사이클(주 진입) | 불가 | 고정 목록·진행 위치·사이클 단위 오답 반복을 저장할 곳이 없음 |
| 홈의 과목별 상태·진행도 | 불가 | 상태를 계산할 사이클 데이터가 없음 |
| 회차별 연습 | 일부 가능 | 회차 문항 조회·채점은 되지만 이어풀기 위치와 재전송 방어가 없음 |
| 모의고사 | 불가 | 채점 API가 제출 즉시 정답을 공개하고 기록함. 답안 임시 저장·일괄 제출·결과 재조회가 없음 |
| 새로고침·재접속·기기 변경 후 복원 | 불가 | 세션 단건 조회조차 없음 |

전면 재설계는 필요 없다. 응답 원장(`study_attempt`), 문항별 누계(`study_state`), 채점·종료 잠금 순서(B-01)는 그대로 둔다. 여기에 **세션의 고정 문항 목록(답안 슬롯)** 과 **과목 사이클** 을 추가하고 그 위에 API를 얹는다.

로컬 DB의 학습 기록은 0행이다(`study_session`·`study_attempt`·`study_state` 모두 비어 있음, 2026-09-11 읽기 전용 조회). 옮길 데이터 없이 스키마를 바꿀 수 있다.

삭제된 `plan/backend-review.md` 는 커밋 메시지에 "모든 항목 반영 완료"로 남았지만, 삭제 직전 문서의 6.3절은 **I-02**(세션 범위 검사·재전송 멱등·이어풀기와 결과 복원)를 설계 대기로 분류했다. 현재 코드에도 반영되어 있지 않다. 4절의 설계가 이 항목을 함께 해소한다.

## 2. 현재 백엔드 확인 결과

### 2.1. API

JSON 엔드포인트 18개. 상세 계약은 `back/README.md`.

| 구분 | 엔드포인트 | 설계서 흐름에서의 쓰임 |
|---|---|---|
| 회차·과목 | `GET /api/subjects`, `/api/exams`, `/api/exams/{examId}`, `/api/exams/{examId}/questions` | 과목·회차 선택에 그대로 사용. 회차 문항 목록은 `limit` 최대 200이라 100문항을 한 번에 받음 |
| 문항 | `GET /api/questions/{questionId}`, `/api/questions/random` | 단건은 사용. 랜덤은 사이클 구성에 쓸 수 없음(2.3절) |
| 채점 | `POST /api/questions/{questionId}/answer` | 응답 형식(`answer`·`explanation`·`keyPoint`·`choicesAnalysis`)은 재사용. 호출할 때마다 원장에 1행이 쌓임 |
| 세션 | `POST /api/sessions`, `GET /api/sessions`, `POST /api/sessions/{id}/finish` | 문항 목록·진행 위치가 없고 단건 조회도 없음 |
| 진도·통계·태그 | `GET·PATCH /api/progress/questions/…`, `GET /api/stats/*`, `GET /api/tags` | 전체 기간 누계 기준. 설계서가 사이클 오답과 구분하므로 이번 흐름에서는 쓰지 않음 |
| 메타 | `GET /api/health`, `/figures/*` | 그대로 사용 |

### 2.2. DB (`app` DB의 `ipe` 스키마)

| 객체 | 역할 | 설계서 흐름과의 관계 |
|---|---|---|
| `subject`·`exam`·`question`·`question_choice`·`tag`·`question_tag` | 문항 데이터(13회차, 1,300문항, 보기 5,200) | 변경 불필요 |
| `study_session` | 학습 묶음: `mode`(`exam`·`subject`·`random`·`review`), 대상 회차·과목, 시작·종료 시각 | 출제 목록·순서·위치를 담는 컬럼이나 하위 테이블이 없음 |
| `study_attempt` | 응답 1건 = 1행인 원장(append-only) | 유지. 같은 세션·문항의 중복 기록을 막는 제약은 없음 |
| `study_state` | 문항당 1행. 전체 기간 누계·북마크·메모·복습 예정일 | 유지. 사이클 오답 판정에는 쓰지 않음 |
| `v_subject_stats`·`v_wrong_questions`·`v_review_due` | 전체 기간 통계 뷰 | 이번 흐름과 무관 |

`tools/load_db.py --init` 은 `db/*.sql` 을 파일명 순서로 **매번 전부** 실행한다. 새 마이그레이션도 재실행에 안전해야 한다.

### 2.3. 사이클 길이와 중복 문항

API의 중복 판정 함수(`back/app/queries.py` 의 `content_key`)를 원본 JSON 1,300문항에 적용해 계산했다.

| 과목 | 문항 | 중복 제거 후 |
|---|---|---|
| 1 소프트웨어 설계 | 260 | 176 |
| 2 소프트웨어 개발 | 260 | 194 |
| 3 데이터베이스 구축 | 260 | 194 |
| 4 프로그래밍 언어 활용 | 260 | 199 |
| 5 정보시스템 구축 관리 | 260 | 181 |

- `GET /api/questions/random` 은 `count` 상한이 100이고 호출할 때마다 새로 뽑는다. 176~199문항의 목록을 한 번에 만들 수 없고, 나눠 부르면 호출 사이에 중복이 생긴다.
- 전체 내용 그룹은 938개다. `AGENTS.md`·`back/README.md` 의 "고유 847개"는 더 느슨하게 정규화하는 `tools/dups.py` 기준이다. 사이클 길이는 API 기준 수치로 안내해야 한다.
- 과목이 다른 문항끼리 묶인 그룹이 6개다(예: `2023-1-001`(1과목)=`2023-1-023`(2과목), `2023-2-076`(4과목)=`2025-3-009`(1과목)). 과목으로 먼저 거른 뒤 묶으므로 이런 문항은 두 과목 사이클에 한 번씩 들어간다.
- 같은 그룹 안에서 정답이 다른 경우는 없다. 대표 문항을 무엇으로 골라도 채점 결과는 같다.

## 3. 설계서 요구사항별 대조

괄호는 `frontend-design.md` 의 절 번호다.

| 설계서 요구 | 현재 | 부족한 점 |
|---|---|---|
| 문제·보기·지문(`code`/`table`/`text`)·도식 표시 (3.1) | 가능 | — |
| 제출 직후 정오답·전체 해설·보기별 설명 (3.1) | 가능 | 채점 응답에 모두 들어 있음 |
| 풀기 전 정답 비노출 (3.1·3.2) | 부족 | 조회 응답의 `state` 에 `lastChoiceNo`·`lastIsCorrect` 가 있어, 전에 맞힌 문항은 정답이 드러남 |
| 과목 문제를 모아 중복 제거·셔플한 목록 구성 (4.1) | 부족 | 랜덤 API는 상한 100에 매번 재추첨. 목록 저장 없음 |
| 사이클 동안 목록 유지, 같은 위치에서 이어풀기 (4.1·6) | 불가 | 세션에 문항 목록·위치가 없고 단건 조회도 없음 |
| 과목을 옮겨도 과목별 진행 유지 (4.1) | 불가 | 과목별 진행 중 사이클 개념이 없음 |
| 이번 사이클의 오답만 반복 복습 후 완료 (4.2) | 불가 | 오답 정보는 전체 기간 누계(`study_state`)뿐 |
| 첫 풀이 성적과 복습 결과 구분 (4.2) | 부족 | 세션별 집계는 있지만 사이클·라운드로 묶이지 않음 |
| 홈의 과목별 상태·진행도·동작 (5) | 불가 | 요약 API 없음 |
| 회차별 연습 (3) | 일부 | 조회·채점은 가능. 이어풀기 위치·재전송 방어 없음. `mode=exam` 이 모의고사 의미라 연습과 구분할 수 없음 |
| 모의고사 풀이 중 결과 비공개 (3.2) | 불가 | 채점 API가 하나뿐이고, 응답에 정답이 담기며 즉시 기록됨 |
| 모의고사 최종 제출 후 채점·해설 (3.2) | 불가 | 일괄 제출 없음. 100번 호출은 원자적이지 않고 끝난 뒤 해설을 다시 볼 조회 API가 없음 |
| 모의고사 답안 수정·미응답 (3.2, 미정) | 불가 | 원장은 수정하지 않는 구조이고 `choice_no` 는 NOT NULL |
| 네트워크 오류 후 재시도 (7) | 불가 | 같은 요청을 두 번 보내면 원장 2행·누계 2회 (I-02) |
| 결과 복기 (6) | 불가 | 해설은 기록을 남기는 채점 응답으로만 받을 수 있음 (I-02) |

## 4. 추가 DB 설계

### 4.1. 방향

세 가지 풀이 방식을 모두 **"고정된 문항 목록을 가진 세션"** 으로 통일한다. 과목 사이클은 이런 세션의 연쇄로 표현한다. 이 문서에서 **라운드**는 사이클 안의 풀이 1회를 뜻한다. 라운드 1은 전체 풀이이고, 라운드 2부터는 직전 라운드 오답의 복습이다.

```text
study_cycle            과목 사이클 (과목당 진행 중 1개)
  │ 1:N  라운드 1 = 전체 풀이, 라운드 2~ = 직전 라운드 오답 복습
  ▼
study_session          사이클의 라운드 1회 · 회차별 연습 1회 · 모의고사 1회
  │ 1:N
  ▼
study_session_item     고정 문항 목록 + 문항당 답안 슬롯 1개 ──▶ question
  │ 채점될 때 같은 트랜잭션에서
  ▼
study_attempt (원장, 기존) ──▶ study_state (누계, 기존)
```

- 라운드를 세션으로 두면 라운드별 `answered`·`correct` 가 기존 세션 집계로 나온다. 첫 풀이 성적과 복습 결과가 자연히 분리된다.
- 목록을 만든 시점에 저장하므로, 이후 중복 판정 규칙이 바뀌어도 진행 중인 사이클은 영향을 받지 않는다.
- 문항당 슬롯이 하나라 재전송이 같은 슬롯을 가리키고, 멱등 처리를 제약으로 보장할 수 있다. 세션에 없는 문항은 제출할 경로가 없으므로 범위 검사 문제(I-02)도 사라진다.
- 모의고사는 제출 전까지 슬롯에만 선택을 저장하고 원장·누계를 건드리지 않는다. 최종 제출 때 한 트랜잭션에서 채점한다.

### 4.2. `study_cycle` (신규)

```sql
CREATE TABLE IF NOT EXISTS ipe.study_cycle (
    id           serial PRIMARY KEY,
    subject_code smallint    NOT NULL REFERENCES ipe.subject(code),
    status       text        NOT NULL DEFAULT 'active',
    created_at   timestamptz NOT NULL DEFAULT now(),
    ended_at     timestamptz,
    CONSTRAINT study_cycle_status_chk CHECK (status IN ('active', 'completed', 'abandoned')),
    CONSTRAINT study_cycle_ended_chk  CHECK ((status = 'active') = (ended_at IS NULL))
);
-- 과목당 진행 중 사이클은 1개
CREATE UNIQUE INDEX IF NOT EXISTS study_cycle_active_uk
    ON ipe.study_cycle (subject_code) WHERE status = 'active';
```

- `completed` 는 어떤 라운드가 오답 없이 끝난 상태, `abandoned` 는 진행 중에 새로 구성한 상태다.
- 사이클 전체 목록은 라운드 1 세션의 슬롯이다. 목록 테이블을 따로 두지 않는다.
- 현재 라운드는 이 사이클의 열린 세션(`finished_at IS NULL`)이다. 값을 컬럼에 중복 저장하지 않는다.

### 4.3. `study_session` 변경

```sql
-- 사이클을 지워도 원장(study_attempt)이 연쇄 삭제되지 않도록 CASCADE 를 걸지 않는다
ALTER TABLE ipe.study_session
    ADD COLUMN IF NOT EXISTS cycle_id   integer REFERENCES ipe.study_cycle(id),
    ADD COLUMN IF NOT EXISTS round_no   smallint,
    ADD COLUMN IF NOT EXISTS end_reason text;

-- 이미 종료된 행이 있으면 사유를 채운다(재실행 안전)
UPDATE ipe.study_session SET end_reason = 'finished'
 WHERE finished_at IS NOT NULL AND end_reason IS NULL;

-- ADD CONSTRAINT 에는 IF NOT EXISTS 가 없어 지우고 다시 만든다(--init 재실행 안전)
ALTER TABLE ipe.study_session DROP CONSTRAINT IF EXISTS study_session_mode_chk;
ALTER TABLE ipe.study_session ADD  CONSTRAINT study_session_mode_chk
    CHECK (mode IN ('subject', 'review', 'exam_practice', 'exam', 'random'));

ALTER TABLE ipe.study_session DROP CONSTRAINT IF EXISTS study_session_round_chk;
ALTER TABLE ipe.study_session ADD  CONSTRAINT study_session_round_chk
    CHECK ((cycle_id IS NULL AND round_no IS NULL)
        OR (cycle_id IS NOT NULL AND ((mode = 'subject' AND round_no = 1)
                                   OR (mode = 'review'  AND round_no >= 2))));

ALTER TABLE ipe.study_session DROP CONSTRAINT IF EXISTS study_session_end_reason_chk;
ALTER TABLE ipe.study_session ADD  CONSTRAINT study_session_end_reason_chk
    CHECK ((finished_at IS NULL) = (end_reason IS NULL)
       AND (end_reason IS NULL OR end_reason IN ('finished', 'abandoned')));

CREATE UNIQUE INDEX IF NOT EXISTS study_session_cycle_round_uk
    ON ipe.study_session (cycle_id, round_no) WHERE cycle_id IS NOT NULL;
-- 사이클당 열린 라운드는 1개
CREATE UNIQUE INDEX IF NOT EXISTS study_session_cycle_open_uk
    ON ipe.study_session (cycle_id) WHERE cycle_id IS NOT NULL AND finished_at IS NULL;
-- 회차별 연습·모의고사는 회차마다 진행 중 1개
CREATE UNIQUE INDEX IF NOT EXISTS study_session_exam_open_uk
    ON ipe.study_session (mode, exam_id)
    WHERE mode IN ('exam_practice', 'exam') AND finished_at IS NULL;
```

변경 후 `mode` 의 의미:

| mode | 쓰임 | 슬롯 구성 | 채점 시점 |
|---|---|---|---|
| `subject` | 과목 사이클 라운드 1(전체 풀이) | 과목 문항을 중복 제거·셔플 | 문항별 즉시 |
| `review` | 과목 사이클 라운드 2~(오답 복습) | 직전 라운드의 오답 | 문항별 즉시 |
| `exam_practice` | 회차별 연습(신규) | 회차 문항 번호 순 | 문항별 즉시 |
| `exam` | 모의고사(기존 의미 유지) | 회차 100문항 번호 순 | 최종 제출 때 일괄 |
| `random` | 기존 랜덤(설계서에 없음) | 슬롯 없음 | 기존 `/answer` |

`finished_at` 은 계속 "더 이상 기록을 받지 않음"을 뜻한다. `end_reason` 은 정상 종료(`finished`)와 중단(`abandoned`)을 구분한다. 기존 `/finish` 의 UPDATE도 `end_reason` 을 함께 채워야 새 CHECK 를 통과하므로, DDL과 같은 변경에 포함한다.

### 4.4. `study_session_item` (신규)

```sql
CREATE TABLE IF NOT EXISTS ipe.study_session_item (
    session_id  integer     NOT NULL REFERENCES ipe.study_session(id) ON DELETE CASCADE,
    seq         smallint    NOT NULL,
    question_id text        NOT NULL REFERENCES ipe.question(id) ON DELETE CASCADE,
    choice_no   smallint,
    is_correct  boolean,
    answered_at timestamptz,
    PRIMARY KEY (session_id, seq),
    CONSTRAINT study_session_item_question_uk  UNIQUE (session_id, question_id),
    CONSTRAINT study_session_item_seq_chk      CHECK (seq >= 1),
    CONSTRAINT study_session_item_choice_chk   CHECK (choice_no IS NULL OR choice_no BETWEEN 1 AND 4),
    CONSTRAINT study_session_item_answered_chk CHECK (choice_no IS NULL OR answered_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS study_session_item_question_idx ON ipe.study_session_item (question_id);
```

| 컬럼 | 연습(`subject`·`review`·`exam_practice`) | 모의고사(`exam`) |
|---|---|---|
| `choice_no` | 제출한 보기. 채점 후 바뀌지 않음 | 현재 고른 보기. 제출 전까지 수정 가능하고 NULL 은 미응답 |
| `is_correct` | 제출 즉시 채움. NULL 이면 아직 풀지 않음 | 최종 제출 때 채움 |
| `answered_at` | 제출 시각 | 마지막으로 선택을 저장한 시각(저장 상태 표시용) |

- 연습 슬롯은 `is_correct IS NULL` 일 때 한 번만 채점한다. 이때 `study_attempt` 1행 추가와 `study_state` 갱신을 같은 트랜잭션에서 처리한다. 채점된 슬롯 1개는 원장 1행에 대응한다.
- 다음에 풀 문항은 `is_correct IS NULL` 인 가장 작은 `seq` 다. 위치 컬럼을 따로 두지 않는다.
- 재적재에서 문항이 사라지면(`load_db.py` 는 JSON에 없는 문항을 지운다) 슬롯도 함께 지워져 `seq` 에 빈 번호가 생길 수 있다. 진행도는 행 수로 계산하고 연속 번호를 가정하지 않는다.

### 4.5. 과목 사이클 목록 구성과 라운드 전환

1. 과목 문항 260개를 모은다.
2. `content_key()` 로 묶는다(랜덤 출제와 같은 기준). 과목별 176~199그룹이 나온다.
3. 그룹마다 대표 1문항을 고른다. 권장 규칙은 **가장 최근 회차의 문항**(`id` 가 가장 큰 것)이다. 결과가 결정적이라 테스트하기 쉽고, 그룹 안에 정답 불일치가 없어 채점에는 영향이 없다.
4. 그룹 순서를 무작위로 섞어 라운드 1 세션의 슬롯(`seq` 1..N)으로 저장한다. 이후 바뀌지 않는다.
5. 마지막 슬롯이 채점되면 같은 트랜잭션에서 라운드를 닫는다. 오답이 있으면 그 문항들로 다음 라운드 세션을 만들고, 없으면 사이클을 `completed` 로 바꾼다. 열린 라운드 1개 인덱스 때문에 현재 라운드 종료를 먼저 기록한 뒤 다음 라운드를 넣는다. 이렇게 하면 "라운드는 끝났는데 다음 라운드가 없는" 중간 상태가 생기지 않는다.

### 4.6. 잠금 순서와 동시성

B-01에서 정한 "세션 행 `FOR UPDATE` 먼저" 규칙을 넓힌다. 모든 쓰기는 **세션 → 슬롯 → 사이클** 순서로 잠근다.

| 경합 | 처리 |
|---|---|
| PC와 휴대폰에서 같은 문항을 동시에 제출 | 뒤 요청은 슬롯 잠금을 기다린 뒤 이미 채점된 슬롯을 본다. 같은 보기면 저장된 결과로 `200`, 다른 보기면 `409` 와 저장된 결과 |
| 마지막 문항 제출과 새로 구성하기가 겹침 | 새로 구성은 열린 세션을 잠근 뒤 아직 열려 있는지 다시 확인하고 나서 사이클을 `abandoned` 로 바꾼다 |
| 두 기기에서 동시에 사이클 시작 | `study_cycle_active_uk` 위반을 `409` 로 돌려주고, 프론트는 홈을 다시 조회 |
| 모의고사 선택 저장과 최종 제출이 겹침 | 둘 다 세션을 먼저 잠그므로 제출 뒤에 도착한 저장은 `409` |

## 5. 추가·변경 API 설계

JSON 키는 기존 규약대로 camelCase이고, 쓰기 요청은 기존 `EXAM_API_TOKEN` 가드를 따른다. 정답·해설은 **채점이 끝난 슬롯**에 한해 조회 응답에 넣는다. 기존의 "조회 응답에는 정답이 없다" 원칙을 슬롯 단위로 넓힌 것이다.

### 5.1. 홈 — `GET /api/subject-cycles/overview`

과목 5개의 상태를 한 번에 돌려준다.

```json
[{
  "subjectCode": 1, "subjectName": "소프트웨어 설계", "uniqueQuestionCount": 176,
  "status": "reviewing",
  "cycle": {
    "id": 3, "startedAt": "2026-09-11T05:25:50Z", "endedAt": null,
    "firstRound":   {"itemCount": 176, "answered": 176, "correct": 150},
    "currentRound": {"sessionId": 12, "roundNo": 2, "itemCount": 26, "answered": 5, "correct": 3}
  }
}]
```

| `status` | 조건 | 홈 동작 |
|---|---|---|
| `not_started` | 진행 중이거나 완료한 사이클이 없음 | 시작하기 |
| `first_pass` | 진행 중 사이클의 열린 라운드가 1 | 이어서 풀기·새로 구성하기 |
| `reviewing` | 진행 중 사이클의 열린 라운드가 2 이상 | 이어서 풀기·새로 구성하기 |
| `completed` | 진행 중 사이클이 없고 완료한 사이클이 있음 | 새로 구성하기 |

- `cycle` 은 진행 중 사이클이고, 없으면 마지막 완료 사이클이다(이때 `currentRound` 는 null). `not_started` 면 null.
- `uniqueQuestionCount` 는 중복 제거 후 문항 수(2.3절)다. 1,300행이라 요청마다 계산해도 부담이 없다.

### 5.2. 과목 사이클

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/subject-cycles` | 본문 `{subjectCode, replaceActive=false}`. 목록을 구성해 라운드 1 세션까지 만든다(`201`). 진행 중 사이클이 있으면 `409`. `replaceActive=true` 면 기존 사이클을 `abandoned` 로 닫고 같은 트랜잭션에서 새로 만든다 |
| GET | `/api/subject-cycles/{cycleId}` | 사이클 상태와 라운드 목록(라운드별 문항 수·정답 수·시작·종료 시각) |
| GET | `/api/subject-cycles` | `subjectCode`·`status`·`limit`·`offset`. 이전 사이클 목록(조회 범위는 6절 결정 사항) |

### 5.3. 세션 슬롯(세 방식 공통)

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/sessions` (변경) | `mode=exam_practice`·`exam` 이면 회차 문항으로 슬롯을 만든다. `replaceActive` 규칙은 5.2와 같다. `subject`·`review` 는 사이클 API로만 만들 수 있게 `400`. `random` 은 기존대로 슬롯 없이 만든다 |
| GET | `/api/sessions/{sessionId}` (신규) | 세션 요약, `itemCount`·`answeredCount`·`nextSeq`(없으면 null), 슬롯 목록 `[{seq, questionId, choiceNo, isCorrect}]`. 진행 중인 모의고사는 `isCorrect` 를 null 로 가린다 |
| GET | `/api/sessions/{sessionId}/items/{seq}` (신규) | `QuestionOut` 과 슬롯 상태, `result`. `result` 는 채점된 연습 슬롯이나 제출된 모의고사일 때만 채점 응답과 같은 형식으로 준다. 채점 전에는 `state` 를 빼서 이전 정답이 드러나지 않게 한다. 조회는 기록을 남기지 않는다 |
| PUT | `/api/sessions/{sessionId}/items/{seq}/answer` (신규) | 본문 `{choiceNo, elapsedMs?}`. **연습**: 채점·기록 후 채점 응답과 진행 정보를 준다. 같은 보기로 이미 채점됐으면 기록 없이 같은 응답(`200`), 다른 보기면 `409`. **모의고사**: 선택만 저장(`choiceNo: null` 은 선택 해제)하고 정답 없이 `{seq, choiceNo, answeredAt}` 을 준다 |
| POST | `/api/sessions/{sessionId}/submit` (신규) | 모의고사 최종 제출. 한 트랜잭션에서 전 문항 채점, 원장·누계 기록, 종료까지 처리한다. 이미 제출됐으면 같은 결과를 돌려준다(멱등) |
| POST | `/api/sessions/{sessionId}/finish` (변경) | 슬롯이 있는 세션은 `409`. 연습은 마지막 문항에서 자동으로 끝나고 모의고사는 `submit` 을 쓴다 |
| POST | `/api/questions/{questionId}/answer` (변경) | `sessionId` 가 슬롯이 있는 세션이면 `409`. `sessionId` 없는 단발 채점은 기존대로 |

연습 채점 응답(`PUT …/answer`)의 구성:

```text
GradeResult 필드 전부
+ session      {id, itemCount, answeredCount, nextSeq, finished}
+ roundResult  이 제출로 세션이 끝났을 때만 {roundNo, itemCount, correct, wrong}
+ cycle        사이클 라운드일 때만 {id, status, nextSessionId, nextRoundNo, nextItemCount}
```

모의고사 제출 응답은 정보처리기사 필기 기준(과목당 20문항, 문항당 5점, **매 과목 40점 이상이면서 전 과목 평균 60점 이상**)으로 계산한 `bySubject[{subjectCode, correct, score, passed}]`·`averageScore`·`passed` 를 담는다. 결과 화면이 정해지면 필드를 조정한다.

### 5.4. 기존 코드에서 함께 정리할 점

- 채점 로직(정답 조회, 원장 INSERT, 누계 upsert, 보기별 해설 조회)을 `questions.py` 에서 공용 모듈(예: `app/grading.py`)로 옮긴다. 기존 `/answer`, 슬롯 제출, 모의고사 일괄 제출이 같은 함수를 쓴다.
- `SessionOut` 에 `cycleId`·`roundNo`·`endReason` 을 더하고, `GET /api/sessions` 에서 이 값으로 거를 수 있게 한다.
- 설계서 흐름에서 쓰지 않는 `random`·`stats/*`·`progress/*`·`tags` 는 그대로 둔다. 지울 이유는 없다.

## 6. 설계서의 미정 항목이 백엔드에 주는 영향

`frontend-design.md` 6절 협의 항목 중 스키마·API 모양을 바꾸는 것만 추렸다. 권장값은 결정 전까지 구현 기본값으로 쓸 수 있는 제안이다.

| 결정할 것 | 백엔드 영향 | 권장 기본값 |
|---|---|---|
| 오답 복습 라운드의 문항 순서 | 다음 라운드 슬롯을 만들 때 섞을지 여부 | 다시 섞기(위치 기억 방지). 구현 비용은 같음 |
| 사이클 진행 중 새로 구성하기 | `replaceActive` 필요 여부 | 확인 대화상자를 거쳐 허용. 기존 사이클은 `abandoned` 로 보존 |
| 모의고사 미응답 문항 | 제출 시 채점 방식과 원장 기록 여부 | 점수는 오답으로 처리, 원장·누계에는 기록하지 않음(`choice_no NOT NULL` 유지) |
| 모의고사 답안 수정·문항 이동 | 슬롯 구조는 모두 지원 | 제출 전 자유 수정 |
| 동시에 열어 둘 모의고사·회차 연습 수 | `study_session_exam_open_uk` 범위 | 회차마다 1개 |
| 회차별 연습의 과목 필터·순서 | 세션 생성 파라미터와 슬롯 구성 | 번호 순, 필터 없음 |
| 회차별 연습에도 오답 반복 적용 | `study_cycle` 에 회차 범위(`exam_id`) 추가 | 1차 구현에서는 제외 |
| 이전 결과 조회 범위 | 이력 목록 API의 필요 범위 | 과목별 최근 사이클과 모의고사 목록부터 |
| 배포와 접근 제어 | 휴대폰에서 쓰려면 외부 접속이 필요함. 현재 GET은 인증이 없고, 쓰기 토큰은 프론트 코드에 넣으면 노출됨. 운영 오리진을 `EXAM_CORS_ORIGINS` 에 추가해야 함 | 배포 방식을 정할 때 함께 결정(구현 순서에는 영향 없음) |

## 7. 구현 순서와 완료 기준

| 단계 | 내용 | 완료 확인 |
|---|---|---|
| 1 | `db/003_study_items.sql`(4.2~4.4절)과 `/finish` 의 `end_reason` 기록 | 빈 DB 재구축과 기존 DB 적용 모두 통과, `--init` 연속 2회 실행 무오류, 기존 테스트 전부 통과 |
| 2 | 채점 공용 함수 분리 | 기존 `/answer` 단위·통합·동시성 테스트 그대로 통과 |
| 3 | 세션 슬롯 API: 단건·문항 조회, 연습 제출, `exam_practice` 생성 | 재전송 멱등, 다른 보기 재제출 `409`, `nextSeq` 이어풀기, 조회가 원장을 늘리지 않음, 채점 전 `state` 비노출. 기존 `mode=subject` 생성 테스트는 `400` 계약으로 갱신 |
| 4 | 과목 사이클: 목록 구성, 라운드 자동 전환, 홈 요약 | 전체 풀이 → 오답 라운드 반복 → 완료, 첫 라운드 전부 정답이면 즉시 완료, 과목당 진행 중 1개, 새로 구성 |
| 5 | 모의고사: 선택 저장, 최종 제출, 결과 | 제출 전 정답 비노출, 선택 저장과 제출 경합, 미응답 처리, 과목별 점수·합격 판정 |
| 6 | 문서: `back/README.md`·`db/README.md`·`AGENTS.md`(중복 문항 수 표기 포함) | OpenAPI와 문서 대조 |

- 과목별 연습이 주 진입이므로 1~4단계를 마치면 설계서의 핵심 흐름을 프론트에 붙일 수 있다. 1~4단계는 6절의 권장 기본값으로 착수할 수 있고, 5단계는 모의고사 항목을 정한 뒤 시작하는 편이 낫다.
- 4.6절의 경합은 가짜 DB로 검출할 수 없다. 기존 `test_integration_concurrency.py` 처럼 실제 PostgreSQL 통합 테스트로 고정한다.

## 8. 확인 근거

- 코드: `back/app/`(라우터 5개·스키마·공용 쿼리), `db/001_schema.sql`·`db/002_progress.sql`, `tools/load_db.py`
- 과목별 중복 제거 수·교차 과목 그룹·정답 불일치: `content_key` 를 원본 JSON 65파일에 적용해 계산
- 학습 기록 행 수와 `ipe` 객체 목록: 로컬 `app.ipe` 읽기 전용 조회
- I-02의 원래 판정: 삭제 직전 `plan/backend-review.md`(`6adb2de^`) 6.3절
