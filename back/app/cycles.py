"""사이클 라운드(슬롯 세션)·슬롯 공용 로직.

- create_round_session: 주어진 문항 id 목록으로 세션과 슬롯을 같은 트랜잭션에서 만든다.
  회차별 연습·모의고사(progress 라우터)와 앞으로의 과목 사이클(4단계)이 함께 쓴다.
- advance_round_if_complete: 마지막 슬롯이 채점되면 라운드를 닫고, 오답이 있으면 다음
  라운드(review)를 만들고 없으면 사이클을 completed 로 바꾼다.

잠금 순서는 세션 → 슬롯 → 사이클이다(설계 4.6절). 호출자가 트랜잭션을 열고 순서를 지킨다.
"""
from __future__ import annotations

import random

from fastapi import HTTPException, status

from .schemas import CycleResultOut, RoundResultOut, SessionProgressOut

# 문항 id 목록을 그대로 슬롯으로 넣는다. seq 는 목록 순서(1..N)다.
SLOT_INSERT_SQL = """
INSERT INTO ipe.study_session_item (session_id, seq, question_id)
SELECT %s, ordinality::smallint, id
  FROM unnest(%s::text[]) WITH ORDINALITY AS t(id, ordinality)
"""

SLOT_COLUMNS = "seq, question_id, choice_no, is_correct, answered_at"
SLOT_SELECT_SQL = f"""
SELECT {SLOT_COLUMNS} FROM ipe.study_session_item WHERE session_id = %s ORDER BY seq
"""
SLOT_SELECT_ONE_SQL = f"""
SELECT {SLOT_COLUMNS} FROM ipe.study_session_item WHERE session_id = %s AND seq = %s
"""
SLOT_LOCK_SQL = f"""
SELECT {SLOT_COLUMNS} FROM ipe.study_session_item
 WHERE session_id = %s AND seq = %s
 FOR UPDATE
"""
# 연습 슬롯 채점: 보기·정오답·시각을 한 번에 채운다. 이미 채점된 슬롯은 호출자가 거른다.
SLOT_GRADE_SQL = """
UPDATE ipe.study_session_item
   SET choice_no = %s, is_correct = %s, answered_at = now()
 WHERE session_id = %s AND seq = %s
"""
# 모의고사 선택 저장: choiceNo=null 은 선택 해제(answered_at 도 비운다).
# 두 번째 %s 는 NULL 이 올 수 있어 타입을 명시한다(psycopg 가 타입을 못 정하는 것 방지).
SLOT_SAVE_SQL = """
UPDATE ipe.study_session_item
   SET choice_no = %s::smallint,
       answered_at = CASE WHEN %s::smallint IS NULL THEN NULL ELSE now() END
 WHERE session_id = %s AND seq = %s
RETURNING choice_no, answered_at
"""
SLOT_PENDING_SQL = """
SELECT count(*)::int AS n FROM ipe.study_session_item
 WHERE session_id = %s AND is_correct IS NULL
"""

# 세션 진행 통계. {pending} 자리에 연습(채점 전)·모의고사(선택 전)의 조건이 들어간다(코드 상수만).
SLOT_STATS_SQL = """
SELECT count(*)::int AS item_count,
       count(choice_no)::int AS answered_count,
       (min(seq) FILTER (WHERE {pending}))::int AS next_seq,
       (count(*) FILTER (WHERE is_correct))::int AS correct_count,
       (count(*) FILTER (WHERE is_correct IS FALSE))::int AS wrong_count
  FROM ipe.study_session_item
 WHERE session_id = %s
"""
PENDING_UNGRADED = "is_correct IS NULL"  # 연습: 아직 채점 안 된 슬롯
PENDING_UNANSWERED = "choice_no IS NULL"  # 모의고사: 선택이 없는 슬롯

SESSION_INSERT_SQL = """
INSERT INTO ipe.study_session (mode, exam_id, subject_code, cycle_id, round_no)
VALUES (%s, %s, %s, %s, %s)
RETURNING id
"""
# 라운드 종료. finished_at 과 end_reason 을 함께 채워야 CHECK 를 통과한다.
ROUND_FINISH_SQL = """
UPDATE ipe.study_session SET finished_at = now(), end_reason = 'finished'
 WHERE id = %s AND finished_at IS NULL
"""

# 회차별 연습·모의고사의 진행 중 세션(같은 모드·회차). 잠그고 나서 다시 확인한다(설계 4.6절).
EXAM_OPEN_SESSION_SQL = """
SELECT id FROM ipe.study_session
 WHERE mode = %s AND exam_id = %s AND finished_at IS NULL
 FOR UPDATE
"""
SESSION_ABANDON_SQL = """
UPDATE ipe.study_session SET finished_at = now(), end_reason = 'abandoned'
 WHERE id = ANY(%s) AND finished_at IS NULL
"""

CYCLE_SELECT_SQL = "SELECT id, subject_code, status FROM ipe.study_cycle WHERE id = %s"
CYCLE_LOCK_SQL = "SELECT id, subject_code, status FROM ipe.study_cycle WHERE id = %s FOR UPDATE"
CYCLE_COMPLETE_SQL = """
UPDATE ipe.study_cycle SET status = 'completed', ended_at = now()
 WHERE id = %s AND status = 'active'
"""
# 사이클의 열린 라운드(현재 세션 제외). 사이클당 1개라 최대 1행이다.
CYCLE_OPEN_SESSION_SQL = """
SELECT s.id, s.round_no,
       (SELECT count(*)::int FROM ipe.study_session_item i WHERE i.session_id = s.id) AS item_count
  FROM ipe.study_session s
 WHERE s.cycle_id = %s AND s.finished_at IS NULL AND s.id <> %s
"""
WRONG_SLOT_SQL = """
SELECT question_id FROM ipe.study_session_item
 WHERE session_id = %s AND is_correct IS FALSE
 ORDER BY seq
"""


def create_round_session(
    conn,
    *,
    mode: str,
    question_ids,
    exam_id: str | None = None,
    subject_code: int | None = None,
    cycle_id: int | None = None,
    round_no: int | None = None,
    shuffle: bool = False,
) -> int:
    """세션 1개 + 슬롯 N개를 만들고 session id 를 돌려준다.

    같은 트랜잭션에서 실행해야 한다(호출자가 트랜잭션을 연다). 슬롯은 목록 순서대로
    seq 1..N 이고, shuffle=True 면 순서를 먼저 섞는다(복습 라운드 권장값).
    """
    ids = list(question_ids)
    if shuffle:
        random.shuffle(ids)
    row = conn.execute(
        SESSION_INSERT_SQL, (mode, exam_id, subject_code, cycle_id, round_no)
    ).fetchone()
    session_id = row["id"]
    if ids:
        conn.execute(SLOT_INSERT_SQL, (session_id, ids))
    return session_id


def replace_open_exam_session(conn, *, mode: str, exam_id: str, replace_active: bool) -> None:
    """회차별 연습·모의고사의 진행 중 세션 처리(설계 5.3절).

    진행 중 세션이 없으면 아무것도 하지 않는다. 있으면 replaceActive=false 는 409,
    true 는 그 세션을 abandoned 로 닫는다 — 새 세션 INSERT 는 호출자가 같은 트랜잭션에서 한다.
    """
    open_ids = [
        row["id"] for row in conn.execute(EXAM_OPEN_SESSION_SQL, (mode, exam_id)).fetchall()
    ]
    if not open_ids:
        return
    if not replace_active:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"이미 진행 중인 {mode} 세션이 있습니다. replaceActive=true 로 새로 구성하세요",
        )
    conn.execute(SESSION_ABANDON_SQL, (open_ids,))


def fetch_slots(conn, session_id: int) -> list[dict]:
    """세션의 슬롯 목록(seq 오름차순). 조회는 아무것도 기록하지 않는다."""
    return conn.execute(SLOT_SELECT_SQL, (session_id,)).fetchall()


def fetch_slot(conn, session_id: int, seq: int) -> dict:
    """슬롯 1개(잠금 없음). 없으면 404."""
    row = conn.execute(SLOT_SELECT_ONE_SQL, (session_id, seq)).fetchone()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"세션 {session_id} 에 {seq}번 문항이 없습니다"
        )
    return row


def lock_slot(conn, session_id: int, seq: int) -> dict:
    """슬롯 행을 FOR UPDATE 로 잠근다(두 번째 잠금). 없으면 404."""
    row = conn.execute(SLOT_LOCK_SQL, (session_id, seq)).fetchone()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"세션 {session_id} 에 {seq}번 문항이 없습니다"
        )
    return row


def grade_slot(conn, session_id: int, seq: int, *, choice_no: int, is_correct: bool) -> None:
    """연습 슬롯에 제출 결과를 기록한다."""
    conn.execute(SLOT_GRADE_SQL, (choice_no, is_correct, session_id, seq))


def save_slot_choice(conn, session_id: int, seq: int, choice_no: int | None) -> dict:
    """모의고사 슬롯에 선택만 저장한다(null 은 선택 해제). 저장된 choice_no·answered_at 을 돌려준다."""
    return conn.execute(SLOT_SAVE_SQL, (choice_no, choice_no, session_id, seq)).fetchone()


def session_progress(conn, session: dict) -> SessionProgressOut:
    """세션 진행(문항 수·답한 수·다음 seq·종료 여부).

    nextSeq 는 연습이면 아직 채점 안 된, 모의고사면 선택이 없는 가장 작은 seq 다.
    종료된 세션은 null. 슬롯이 없는 랜덤 세션은 0/null 이다.
    """
    pending = PENDING_UNANSWERED if session["mode"] == "exam" else PENDING_UNGRADED
    stats = conn.execute(SLOT_STATS_SQL.format(pending=pending), (session["id"],)).fetchone()
    finished = session["finished_at"] is not None
    return SessionProgressOut(
        id=session["id"],
        item_count=stats["item_count"],
        answered_count=stats["answered_count"],
        next_seq=None if finished else stats["next_seq"],
        finished=finished,
    )


def round_result(conn, session: dict) -> RoundResultOut | None:
    """세션이 끝났을 때만 라운드 성적. 진행 중이면 null."""
    if session["finished_at"] is None:
        return None
    stats = conn.execute(
        SLOT_STATS_SQL.format(pending=PENDING_UNGRADED), (session["id"],)
    ).fetchone()
    return RoundResultOut(
        round_no=session["round_no"],
        item_count=stats["item_count"],
        correct=stats["correct_count"],
        wrong=stats["wrong_count"],
    )


def cycle_result(conn, session: dict) -> CycleResultOut | None:
    """세션이 사이클 라운드일 때만 사이클 상태와 다음 라운드 정보. 아니면 null."""
    cycle_id = session["cycle_id"]
    if cycle_id is None:
        return None
    cycle = conn.execute(CYCLE_SELECT_SQL, (cycle_id,)).fetchone()
    if cycle is None:
        return None
    nxt = conn.execute(CYCLE_OPEN_SESSION_SQL, (cycle_id, session["id"])).fetchone()
    return CycleResultOut(
        id=cycle["id"],
        status=cycle["status"],
        next_session_id=nxt["id"] if nxt else None,
        next_round_no=nxt["round_no"] if nxt else None,
        next_item_count=nxt["item_count"] if nxt else None,
    )


def advance_round_if_complete(conn, session: dict) -> bool:
    """채점 안 된 슬롯이 남아 있지 않으면 라운드를 닫는다. 실제로 닫았으면 True.

    - 세션 잠금은 호출자가 이미 잡았다(세션 → 슬롯 → 사이클).
    - cycle_id 가 있으면 사이클을 잠그고, 오답이 있으면 review 라운드를 만들어 이어 가고
      없으면 사이클을 completed 로 바꾼다. 라운드 종료와 다음 라운드 생성이 같은 트랜잭션이라
      '라운드는 끝났는데 다음 라운드가 없는' 중간 상태가 남지 않는다(설계 4.5절).
    """
    pending = conn.execute(SLOT_PENDING_SQL, (session["id"],)).fetchone()["n"]
    if pending:
        return False
    # 사이클당 열린 라운드 1개 인덱스 때문에 현재 라운드를 먼저 닫고 다음 라운드를 넣는다.
    conn.execute(ROUND_FINISH_SQL, (session["id"],))
    if session["cycle_id"] is None:
        return True
    cycle = conn.execute(CYCLE_LOCK_SQL, (session["cycle_id"],)).fetchone()
    if cycle is None or cycle["status"] != "active":
        return True
    wrong_ids = [
        row["question_id"] for row in conn.execute(WRONG_SLOT_SQL, (session["id"],)).fetchall()
    ]
    if not wrong_ids:
        conn.execute(CYCLE_COMPLETE_SQL, (cycle["id"],))
        return True
    create_round_session(
        conn,
        mode="review",
        question_ids=wrong_ids,
        subject_code=cycle["subject_code"],
        cycle_id=cycle["id"],
        round_no=session["round_no"] + 1,
        shuffle=True,
    )
    return True
