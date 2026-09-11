-- ipe 진도 관리 DDL. db/001_schema.sql 다음에 실행한다.
-- 로그인 없는 단일 사용자 기준의 최소 구조(english.study_session/word_result/study_state 와 같은 결).
--   cd /c/dev/exam && python -c "import sys; sys.path.insert(0,'tools'); from load_db import connect; import pathlib; conn=connect(); conn.execute(pathlib.Path('db/002_progress.sql').read_text(encoding='utf-8')); conn.commit()"
-- psql 로 직접 실행해도 된다:
--   docker exec -i postgres psql -U yangyag -d app -f - < db/002_progress.sql
-- 재실행 안전(IF NOT EXISTS / CREATE OR REPLACE VIEW).
-- 되돌리기:
--   DROP VIEW  IF EXISTS ipe.v_review_due, ipe.v_wrong_questions, ipe.v_subject_stats;
--   DROP TABLE IF EXISTS ipe.study_attempt, ipe.study_state, ipe.study_session;

-- 한 번의 학습/응시 묶음. 모드별로 대상(exam_id, subject_code)을 지정하고 없으면 NULL.
CREATE TABLE IF NOT EXISTS ipe.study_session (
    id           serial PRIMARY KEY,
    mode         text        NOT NULL,
    exam_id      text        REFERENCES ipe.exam(id) ON DELETE CASCADE,
    subject_code smallint    REFERENCES ipe.subject(code) ON DELETE CASCADE,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    CONSTRAINT study_session_mode_chk CHECK (mode IN ('exam', 'subject', 'random', 'review')),
    CONSTRAINT study_session_finish_chk CHECK (finished_at IS NULL OR finished_at >= started_at)
);
COMMENT ON TABLE ipe.study_session IS '학습/응시 묶음 1건. mode: exam(회차 모의고사)·subject(과목 연습)·random(랜덤)·review(오답 복습)';
COMMENT ON COLUMN ipe.study_session.exam_id IS '대상 회차. 랜덤·오답 복습처럼 특정 회차가 아니면 NULL';
COMMENT ON COLUMN ipe.study_session.subject_code IS '대상 과목. 회차 모의고사처럼 전체 과목이면 NULL';
COMMENT ON COLUMN ipe.study_session.finished_at IS '종료 시각. NULL 이면 진행 중';

-- 문항별 응답 이력(append-only). 통계·복기용 원장.
CREATE TABLE IF NOT EXISTS ipe.study_attempt (
    id          serial PRIMARY KEY,
    session_id  integer     REFERENCES ipe.study_session(id) ON DELETE CASCADE,
    question_id text        NOT NULL REFERENCES ipe.question(id) ON DELETE CASCADE,
    choice_no   smallint    NOT NULL,
    is_correct  boolean     NOT NULL,
    elapsed_ms  integer,
    answered_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT study_attempt_choice_chk CHECK (choice_no BETWEEN 1 AND 4),
    CONSTRAINT study_attempt_elapsed_chk CHECK (elapsed_ms IS NULL OR elapsed_ms >= 0)
);
COMMENT ON TABLE ipe.study_attempt IS '문항별 응답 1건 = 1행. 수정하지 않고 쌓기만 한다';
COMMENT ON COLUMN ipe.study_attempt.session_id IS '세션 밖 단발 풀이(오답 확인 등)는 NULL';
COMMENT ON COLUMN ipe.study_attempt.choice_no IS '사용자가 고른 보기 번호(1~4). 정답 번호는 ipe.question.answer';
COMMENT ON COLUMN ipe.study_attempt.elapsed_ms IS '응답까지 걸린 시간(ms). 모르면 NULL';

-- 문항당 1행인 현재 상태. 목록·복습 화면이 이 테이블만 보면 되도록 비정규화해 둔다.
CREATE TABLE IF NOT EXISTS ipe.study_state (
    question_id      text PRIMARY KEY REFERENCES ipe.question(id) ON DELETE CASCADE,
    attempt_count    integer     NOT NULL DEFAULT 0,
    correct_count    integer     NOT NULL DEFAULT 0,
    wrong_count      integer     NOT NULL DEFAULT 0,
    last_is_correct  boolean,
    last_choice_no   smallint,
    last_answered_at timestamptz,
    streak           integer     NOT NULL DEFAULT 0,
    bookmarked       boolean     NOT NULL DEFAULT false,
    note             text,
    review_due_on    date,
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT study_state_counts_chk CHECK (correct_count + wrong_count = attempt_count),
    CONSTRAINT study_state_last_choice_chk CHECK (last_choice_no IS NULL OR last_choice_no BETWEEN 1 AND 4),
    CONSTRAINT study_state_streak_chk CHECK (streak >= 0)
);
COMMENT ON TABLE ipe.study_state IS '문항별 현재 상태 1행. 응답할 때마다 갱신한다(연속 정답·북마크·복습 예정일)';
COMMENT ON COLUMN ipe.study_state.streak IS '연속 정답 수. 틀리면 0으로 되돌린다';
COMMENT ON COLUMN ipe.study_state.note IS '오답 메모(자유 입력)';
COMMENT ON COLUMN ipe.study_state.review_due_on IS '복습 예정일. NULL 이면 아직 예약 안 함';

CREATE INDEX IF NOT EXISTS study_session_started_idx   ON ipe.study_session (started_at DESC);
CREATE INDEX IF NOT EXISTS study_session_exam_idx      ON ipe.study_session (exam_id);
CREATE INDEX IF NOT EXISTS study_session_subject_idx   ON ipe.study_session (subject_code);
CREATE INDEX IF NOT EXISTS study_attempt_question_idx  ON ipe.study_attempt (question_id);
CREATE INDEX IF NOT EXISTS study_attempt_session_idx   ON ipe.study_attempt (session_id);
CREATE INDEX IF NOT EXISTS study_attempt_answered_idx  ON ipe.study_attempt (answered_at DESC);
CREATE INDEX IF NOT EXISTS study_attempt_wrong_idx     ON ipe.study_attempt (question_id) WHERE NOT is_correct;
CREATE INDEX IF NOT EXISTS study_state_review_idx      ON ipe.study_state (review_due_on) WHERE review_due_on IS NOT NULL;
CREATE INDEX IF NOT EXISTS study_state_bookmark_idx    ON ipe.study_state (question_id) WHERE bookmarked;
CREATE INDEX IF NOT EXISTS study_state_answered_idx    ON ipe.study_state (last_answered_at DESC NULLS LAST);

-- 과목별 정답률. 응답 기록(study_attempt) 기준이고, 응답 없는 과목도 행이 나온다.
CREATE OR REPLACE VIEW ipe.v_subject_stats AS
SELECT sj.code                                   AS subject_code,
       sj.name                                   AS subject_name,
       count(a.id)                               AS answered,
       count(a.id) FILTER (WHERE a.is_correct)   AS correct,
       count(a.id) FILTER (WHERE NOT a.is_correct) AS wrong,
       count(DISTINCT q.id)                      AS questions_total,
       count(DISTINCT a.question_id)             AS questions_seen,
       round(100.0 * count(a.id) FILTER (WHERE a.is_correct) / nullif(count(a.id), 0), 1) AS accuracy_pct
FROM ipe.subject sj
LEFT JOIN ipe.question q       ON q.subject_code = sj.code
LEFT JOIN ipe.study_attempt a  ON a.question_id = q.id
GROUP BY sj.code, sj.name
ORDER BY sj.code;
COMMENT ON VIEW ipe.v_subject_stats IS '과목별 응답 수·정답률(%)·학습한 문항 수. 응답 0건 과목은 answered=0, accuracy_pct=NULL';

-- 오답 문항 목록(현재 상태 기준). 한 번이라도 틀린 문항을 최근 응답 순으로.
CREATE OR REPLACE VIEW ipe.v_wrong_questions AS
SELECT q.id            AS question_id,
       q.exam_id,
       q.number,
       q.subject_code,
       sj.name         AS subject_name,
       q.stem,
       q.answer,
       st.attempt_count,
       st.wrong_count,
       st.last_choice_no,
       st.last_is_correct,
       st.last_answered_at,
       st.bookmarked,
       st.note,
       st.review_due_on
FROM ipe.study_state st
JOIN ipe.question q ON q.id = st.question_id
JOIN ipe.subject sj ON sj.code = q.subject_code
WHERE st.wrong_count > 0
ORDER BY st.last_answered_at DESC NULLS LAST, q.id;
COMMENT ON VIEW ipe.v_wrong_questions IS '한 번이라도 틀린 문항. last_is_correct 로 미해결 오답만 골라 쓸 수 있다';

-- 복습 예정 문항(오늘까지). 모르면 review_due_on 을 채워 넣으면 여기에 뜬다.
CREATE OR REPLACE VIEW ipe.v_review_due AS
SELECT q.id            AS question_id,
       q.exam_id,
       q.number,
       q.subject_code,
       sj.name         AS subject_name,
       q.stem,
       q.answer,
       st.review_due_on,
       current_date - st.review_due_on AS overdue_days,
       st.last_is_correct,
       st.wrong_count,
       st.note
FROM ipe.study_state st
JOIN ipe.question q ON q.id = st.question_id
JOIN ipe.subject sj ON sj.code = q.subject_code
WHERE st.review_due_on IS NOT NULL
  AND st.review_due_on <= current_date
ORDER BY st.review_due_on, q.id;
COMMENT ON VIEW ipe.v_review_due IS '복습 예정일이 오늘 이하인 문항. overdue_days=0 이면 오늘, 클수록 밀린 것';
