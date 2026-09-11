-- ipe 스키마 DDL. exam 역할(스키마 소유자)로 실행한다.
--   python tools/load_db.py --init
-- psql 로 직접 실행해도 된다:
--   docker exec -i postgres psql -U exam -d app -f - < db/001_schema.sql
-- 재실행 안전(IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS ipe.subject (
    code    smallint PRIMARY KEY,
    name    text     NOT NULL,
    from_no smallint NOT NULL,
    to_no   smallint NOT NULL,
    CONSTRAINT subject_range_chk CHECK (from_no <= to_no)
);
COMMENT ON TABLE ipe.subject IS '과목 (1~5과목, 각 20문항)';

CREATE TABLE IF NOT EXISTS ipe.exam (
    id         text PRIMARY KEY,
    year       smallint    NOT NULL,
    round      smallint    NOT NULL,
    title      text        NOT NULL,
    source_pdf text        NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT exam_year_round_uk UNIQUE (year, round)
);
COMMENT ON TABLE ipe.exam IS '회차. id 형식 2026-1';

CREATE TABLE IF NOT EXISTS ipe.question (
    id               text PRIMARY KEY,
    exam_id          text     NOT NULL REFERENCES ipe.exam(id) ON DELETE CASCADE,
    number           smallint NOT NULL,
    subject_code     smallint NOT NULL REFERENCES ipe.subject(code),
    stem             text     NOT NULL,
    passage          text,
    passage_kind     text,
    answer           smallint NOT NULL,
    explanation      text     NOT NULL,
    key_point        text,
    difficulty       smallint,
    figure_needed    boolean  NOT NULL DEFAULT false,
    figure_kind      text,
    figure_image     text,
    figure_alt       text,
    figure_page      smallint,
    figure_col       smallint,
    figure_box       real[],
    source_pdf       text     NOT NULL,
    source_page      smallint NOT NULL,
    prov_answer      text     NOT NULL,
    prov_explanation text     NOT NULL,
    doc              jsonb    NOT NULL,
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT question_exam_number_uk UNIQUE (exam_id, number),
    CONSTRAINT question_number_chk CHECK (number BETWEEN 1 AND 100),
    CONSTRAINT question_answer_chk CHECK (answer BETWEEN 1 AND 4),
    CONSTRAINT question_difficulty_chk CHECK (difficulty IS NULL OR difficulty BETWEEN 1 AND 5),
    CONSTRAINT question_passage_kind_chk CHECK (passage_kind IS NULL OR passage_kind IN ('code', 'table', 'text')),
    CONSTRAINT question_figure_kind_chk CHECK (figure_kind IS NULL OR figure_kind IN ('diagram', 'screen')),
    CONSTRAINT question_figure_col_chk CHECK (figure_col IS NULL OR figure_col IN (0, 1)),
    CONSTRAINT question_figure_box_chk CHECK (figure_box IS NULL OR array_length(figure_box, 1) = 4),
    CONSTRAINT question_prov_answer_chk CHECK (prov_answer IN ('pdf', 'derived')),
    CONSTRAINT question_prov_explanation_chk CHECK (prov_explanation IN ('pdf', 'generated')),
    CONSTRAINT question_passage_pair_chk CHECK ((passage IS NULL) = (passage_kind IS NULL)),
    CONSTRAINT question_figure_pair_chk CHECK ((figure_image IS NULL) = (figure_box IS NULL)),
    CONSTRAINT question_figure_image_chk CHECK (NOT figure_needed OR figure_image IS NOT NULL)
);
COMMENT ON TABLE ipe.question IS '문항 1,300개. doc 에 원본 JSON 보관';
COMMENT ON COLUMN ipe.question.doc IS '원본 JSON 문서(재이관 없이 복구용)';
COMMENT ON COLUMN ipe.question.figure_image IS 'data/ 기준 상대경로. 그림은 파일로 서빙한다';

CREATE TABLE IF NOT EXISTS ipe.question_choice (
    question_id text     NOT NULL REFERENCES ipe.question(id) ON DELETE CASCADE,
    no          smallint NOT NULL,
    text        text     NOT NULL,
    is_correct  boolean  NOT NULL,
    why         text     NOT NULL,
    PRIMARY KEY (question_id, no),
    CONSTRAINT question_choice_no_chk CHECK (no BETWEEN 1 AND 4)
);
COMMENT ON TABLE ipe.question_choice IS '보기 4개. 보기별 정답 여부와 해설(왜 맞는지/틀린지)까지 포함';

CREATE TABLE IF NOT EXISTS ipe.tag (
    id   serial PRIMARY KEY,
    name text   NOT NULL UNIQUE
);
COMMENT ON TABLE ipe.tag IS '복습용 키워드';

CREATE TABLE IF NOT EXISTS ipe.question_tag (
    question_id text    NOT NULL REFERENCES ipe.question(id) ON DELETE CASCADE,
    tag_id      integer NOT NULL REFERENCES ipe.tag(id) ON DELETE CASCADE,
    PRIMARY KEY (question_id, tag_id)
);
COMMENT ON TABLE ipe.question_tag IS '문항-태그 연결';

CREATE INDEX IF NOT EXISTS question_exam_idx       ON ipe.question (exam_id);
CREATE INDEX IF NOT EXISTS question_subject_idx    ON ipe.question (subject_code);
CREATE INDEX IF NOT EXISTS question_difficulty_idx ON ipe.question (difficulty);
CREATE INDEX IF NOT EXISTS question_figure_idx     ON ipe.question (exam_id) WHERE figure_needed;
CREATE INDEX IF NOT EXISTS question_choice_q_idx   ON ipe.question_choice (question_id);
CREATE INDEX IF NOT EXISTS question_tag_tag_idx    ON ipe.question_tag (tag_id);

-- 부분일치 검색(pg_trgm). 확장이 없으면 건너뛴다.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
        CREATE INDEX IF NOT EXISTS question_stem_trgm_idx ON ipe.question USING gin (stem ipe.gin_trgm_ops);
        CREATE INDEX IF NOT EXISTS question_expl_trgm_idx ON ipe.question USING gin (explanation ipe.gin_trgm_ops);
        RAISE NOTICE 'pg_trgm 인덱스 생성 완료';
    ELSE
        RAISE NOTICE 'pg_trgm 없음: 부분일치 인덱스를 건너뜀';
    END IF;
END
$$;
