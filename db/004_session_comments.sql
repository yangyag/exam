-- study_session 코멘트 정정(모의고사 최종 제출 반영). db/003_study_items.sql 다음에 실행한다.
-- db/002_progress.sql 이 찍은 study_session·exam_id·subject_code 코멘트는 옛 4모드
-- ('exam'·'subject'·'random'·'review') 기준이라, 지금의 5모드 의미(study_session_mode_chk)와
-- 값의 규칙에 맞게 다시 찍는다. mode 컬럼에는 코멘트가 없어 이번에 처음 붙인다.
--
-- 재실행 안전: COMMENT 는 값을 덮어쓸 뿐이라 몇 번 실행해도 결과가 같다
-- (python tools/load_db.py --init 이 db/*.sql 을 매번 전부 실행한다).
-- 003 은 건드리지 않는다 — 003 이 찍은 cycle_id·round_no 와 study_cycle·study_session_item
-- 코멘트는 그대로 두고, 여기서는 study_session 의 테이블·mode·exam_id·subject_code·end_reason 만 다시 찍는다.
-- 되돌리기: 테이블·exam_id·subject_code 는 db/002_progress.sql(22~24행) 값으로 다시 찍고,
-- end_reason 은 이 파일 이전 값이 db/003_study_items.sql(65행)에 있으므로 그 문구를 다시 찍으며,
-- mode 는 이 파일이 최초로 붙였으므로 COMMENT ON COLUMN ipe.study_session.mode IS NULL 로 지운다.
-- (사람이 붙여 넣을 SQL 은 db/README.md 진도 관리 '적용' 절의 되돌리기 블록에 있다.)

COMMENT ON TABLE ipe.study_session IS '학습/응시 묶음 1건. mode 5종: subject(과목 사이클 라운드 1)·review(사이클 라운드 2+, 직전 라운드 오답 복습)·exam_practice(회차별 연습)·exam(회차 모의고사)·random(슬롯 없는 랜덤)';
COMMENT ON COLUMN ipe.study_session.mode IS 'subject(과목 사이클 라운드 1)·review(사이클 라운드 2+, 직전 라운드 오답 복습)·exam_practice(회차별 연습)·exam(회차 모의고사)·random(슬롯 없는 랜덤 출제). 회차 연습·모의고사·사이클 라운드는 슬롯(study_session_item)을 가진다';
COMMENT ON COLUMN ipe.study_session.exam_id IS '대상 회차. exam_practice·exam 은 필수, random 은 요청값 그대로(보통 NULL), 사이클 라운드(subject·review)는 NULL';
COMMENT ON COLUMN ipe.study_session.subject_code IS '대상 과목. 사이클 라운드(subject·review)는 사이클의 과목, random 은 요청값 그대로, exam_practice·exam 은 요청에 있어도 NULL';
COMMENT ON COLUMN ipe.study_session.end_reason IS '종료 사유. finished(정상 종료 — 연습은 마지막 문항 채점, 모의고사는 최종 제출, random 은 /finish)·abandoned(새로 구성으로 중단, 보존). 진행 중이면 NULL';
