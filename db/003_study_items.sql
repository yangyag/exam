-- 슬롯 기반 세션(study_session_item)과 과목 사이클(study_cycle) DDL. db/002_progress.sql 다음에 실행한다.
-- 설계 정본: plan/frontend-backend-gap.md 4.2~4.4절.
-- 적용: python tools/load_db.py --init  (db/*.sql 을 파일명 순서로 매번 전부 실행)
-- 재실행 안전: IF NOT EXISTS / DROP CONSTRAINT IF EXISTS / CREATE UNIQUE INDEX IF NOT EXISTS.
-- 되돌리기:
--   ALTER TABLE ipe.study_session
--       DROP CONSTRAINT IF EXISTS study_session_end_reason_chk,
--       DROP CONSTRAINT IF EXISTS study_session_round_chk,
--       DROP CONSTRAINT IF EXISTS study_session_mode_chk,
--       DROP COLUMN IF EXISTS end_reason,
--       DROP COLUMN IF EXISTS round_no,
--       DROP COLUMN IF EXISTS cycle_id;
--   DROP TABLE IF EXISTS ipe.study_session_item, ipe.study_cycle;
--   (study_session 의 mode CHECK 는 002_progress.sql 의 원래 정의로 다시 만든다)

-- 과목 학습 사이클. 과목당 진행 중(active) 사이클은 1개다.
-- completed = 어떤 라운드가 오답 없이 끝난 상태, abandoned = 진행 중에 새로 구성한 상태(보존).
CREATE TABLE IF NOT EXISTS ipe.study_cycle (
    id           serial PRIMARY KEY,
    subject_code smallint    NOT NULL REFERENCES ipe.subject(code),
    status       text        NOT NULL DEFAULT 'active',
    created_at   timestamptz NOT NULL DEFAULT now(),
    ended_at     timestamptz,
    CONSTRAINT study_cycle_status_chk CHECK (status IN ('active', 'completed', 'abandoned')),
    CONSTRAINT study_cycle_ended_chk  CHECK ((status = 'active') = (ended_at IS NULL))
);
COMMENT ON TABLE ipe.study_cycle IS '과목 학습 사이클. 라운드 1(전체 풀이)~N(오답 복습)의 연쇄';
COMMENT ON COLUMN ipe.study_cycle.status IS 'active(진행 중)·completed(오답 없이 끝남)·abandoned(새로 구성으로 중단)';
COMMENT ON COLUMN ipe.study_cycle.ended_at IS '종료 시각. active 이면 NULL';
-- 과목당 진행 중 사이클은 1개.
CREATE UNIQUE INDEX IF NOT EXISTS study_cycle_active_uk
    ON ipe.study_cycle (subject_code) WHERE status = 'active';

-- study_session 변경: 사이클 라운드(cycle_id·round_no)와 종료 사유(end_reason) 추가.
-- cycle_id 에 CASCADE 를 걸지 않는다 — 사이클 행을 지워도 세션·원장(study_attempt)이 연쇄 삭제되지 않게.
ALTER TABLE ipe.study_session
    ADD COLUMN IF NOT EXISTS cycle_id   integer REFERENCES ipe.study_cycle(id),
    ADD COLUMN IF NOT EXISTS round_no   smallint,
    ADD COLUMN IF NOT EXISTS end_reason text;

-- 이미 종료된 행(운영 DB 마이그레이션)이 있으면 사유를 채운다. 재실행해도 같은 결과다.
UPDATE ipe.study_session SET end_reason = 'finished'
 WHERE finished_at IS NOT NULL AND end_reason IS NULL;

-- ADD CONSTRAINT 에는 IF NOT EXISTS 가 없어 지우고 다시 만든다(--init 재실행 안전).
ALTER TABLE ipe.study_session DROP CONSTRAINT IF EXISTS study_session_mode_chk;
ALTER TABLE ipe.study_session ADD  CONSTRAINT study_session_mode_chk
    CHECK (mode IN ('subject', 'review', 'exam_practice', 'exam', 'random'));

-- 사이클 라운드 세션만 cycle_id·round_no 를 가진다. 라운드 1은 subject, 2부터는 review.
ALTER TABLE ipe.study_session DROP CONSTRAINT IF EXISTS study_session_round_chk;
ALTER TABLE ipe.study_session ADD  CONSTRAINT study_session_round_chk
    CHECK ((cycle_id IS NULL AND round_no IS NULL)
        OR (cycle_id IS NOT NULL AND ((mode = 'subject' AND round_no = 1)
                                   OR (mode = 'review'  AND round_no >= 2))));

-- finished_at 은 '더 이상 기록을 받지 않음', end_reason 은 정상 종료(finished)와 중단(abandoned) 구분.
ALTER TABLE ipe.study_session DROP CONSTRAINT IF EXISTS study_session_end_reason_chk;
ALTER TABLE ipe.study_session ADD  CONSTRAINT study_session_end_reason_chk
    CHECK ((finished_at IS NULL) = (end_reason IS NULL)
       AND (end_reason IS NULL OR end_reason IN ('finished', 'abandoned')));

COMMENT ON COLUMN ipe.study_session.cycle_id IS '과목 사이클 라운드면 그 사이클. 회차 연습·모의고사·랜덤은 NULL';
COMMENT ON COLUMN ipe.study_session.round_no IS '사이클 안의 라운드 번호. cycle_id 가 NULL 이면 NULL';
COMMENT ON COLUMN ipe.study_session.end_reason IS '종료 사유. finished(정상 종료)·abandoned(중단). 진행 중이면 NULL';

-- 사이클의 라운드 번호는 중복될 수 없다.
CREATE UNIQUE INDEX IF NOT EXISTS study_session_cycle_round_uk
    ON ipe.study_session (cycle_id, round_no) WHERE cycle_id IS NOT NULL;
-- 사이클당 열린 라운드는 1개.
CREATE UNIQUE INDEX IF NOT EXISTS study_session_cycle_open_uk
    ON ipe.study_session (cycle_id) WHERE cycle_id IS NOT NULL AND finished_at IS NULL;
-- 회차별 연습·모의고사는 (모드, 회차)마다 진행 중 1개.
CREATE UNIQUE INDEX IF NOT EXISTS study_session_exam_open_uk
    ON ipe.study_session (mode, exam_id)
    WHERE mode IN ('exam_practice', 'exam') AND finished_at IS NULL;

-- 세션의 고정 문항 목록 + 문항당 답안 슬롯 1개.
--   연습(subject·review·exam_practice): choice_no 는 제출한 보기, is_correct 는 채점 결과(채점 후 불변).
--   모의고사(exam): choice_no 는 현재 고른 보기(제출 전 수정 가능, NULL 은 미응답), is_correct 는 최종 제출 때 채점.
--   answered_at: 연습은 제출 시각, 모의고사는 마지막 선택 저장 시각.
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
COMMENT ON TABLE ipe.study_session_item IS '세션의 고정 문항 목록 겸 답안 슬롯(문항당 1개). 목록을 만든 뒤 바뀌지 않는다';
COMMENT ON COLUMN ipe.study_session_item.seq IS '목록에서의 순서(1부터). 다음에 풀 문항은 is_correct 가 NULL 인 가장 작은 seq';
COMMENT ON COLUMN ipe.study_session_item.choice_no IS '연습은 제출한 보기(채점 후 불변), 모의고사는 현재 고른 보기(NULL=미응답)';
COMMENT ON COLUMN ipe.study_session_item.is_correct IS '연습은 제출 즉시, 모의고사는 최종 제출 때 채움. NULL 이면 아직 안 풂';
COMMENT ON COLUMN ipe.study_session_item.answered_at IS '연습은 제출 시각, 모의고사는 마지막으로 선택을 저장한 시각';
CREATE INDEX IF NOT EXISTS study_session_item_question_idx ON ipe.study_session_item (question_id);
