"""실제 PostgreSQL 에서 채점과 세션 종료가 겹칠 때의 순서를 고정한다(B-01 회귀).

가짜 커넥션의 SQL 확인만으로는 트랜잭션 잠금 순서를 검출할 수 없어 실제 DB 에 붙는다.
- study_attempt 에 SHARE 잠금을 걸어 채점의 INSERT 를 멈춰 세운다(리뷰의 재현 기법).
  그러면 채점은 세션 행 잠금(FOR UPDATE)만 쥔 채 대기한다.
- 그 상태를 별도 커넥션의 FOR UPDATE NOWAIT 프로브로 판정한 뒤 /finish 를 보낸다.
  SHARE 를 풀면 채점이 기록을 마치고, 종료는 그 채점을 포함해 집계해야 한다.
- SHARE 잠금은 테스트 한 번에 수백 ms 로 짧게 유지하고 finally 에서 반드시 푼다
  (같은 DB 를 쓰는 다른 테스트의 INSERT 를 오래 막지 않기 위함).
"""
from __future__ import annotations

import threading
import time

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app import db as app_db
from app.config import get_settings
from app.main import app as fastapi_app

from test_integration_db import (
    ProgressTracker,
    auth_headers,
    counters,
    create_session,
    get_attempts,
    pick_question,
    post_answer,
)

pytestmark = pytest.mark.integration


@pytest.fixture()
def db_conn():
    """백엔드와 같은 조건의 직접 커넥션. 접속할 수 없으면 건너뛴다."""
    settings = get_settings()
    try:
        conn = psycopg.connect(
            settings.db_url,
            autocommit=True,
            row_factory=dict_row,
            options=f"-c search_path={app_db.SEARCH_PATH}",
        )
        conn.execute("SELECT 1")
    except psycopg.Error as exc:
        pytest.skip(f"ipe DB 에 접속할 수 없어 건너뛴다 ({exc.__class__.__name__}): {exc}")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture()
def tracker(db_conn):
    """테스트가 만든 진도 행을 되돌리는 추적기(test_integration_db 와 같은 규칙)."""
    progress = ProgressTracker(db_conn)
    yield progress
    progress.cleanup()
    progress.verify_restored()


@pytest.fixture()
def live_client(db_conn, tracker):
    """lifespan(=DB 커넥션 풀)을 실제로 돌리는 TestClient."""
    with TestClient(fastapi_app) as client:
        yield client


def lock_connection(autocommit: bool) -> psycopg.Connection:
    """잠금 실험용 직접 커넥션(백엔드와 같은 search_path)."""
    return psycopg.connect(
        get_settings().db_url,
        autocommit=autocommit,
        row_factory=dict_row,
        options=f"-c search_path={app_db.SEARCH_PATH}",
    )


def holds_session_lock(conn: psycopg.Connection, session_id: int) -> bool:
    """다른 트랜잭션이 그 세션 행을 잠그고 있는지 FOR UPDATE NOWAIT 로 판정한다.

    autocommit 연결이라 잠금이 잡히더라도 그 문장이 끝나면 바로 풀린다.
    """
    try:
        conn.execute(
            "SELECT 1 FROM ipe.study_session WHERE id = %s FOR UPDATE NOWAIT", (session_id,)
        )
        return False
    except psycopg.errors.LockNotAvailable:
        return True


def wait_until(predicate, timeout: float = 5.0, interval: float = 0.02) -> None:
    """조건이 참이 될 때까지 짧게 폴링한다. 시간 안에 참이 되지 않으면 실패한다."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(f"{timeout}초 안에 조건이 참이 되지 않았다")


def test_finish_waits_for_grading_that_holds_the_session_lock(live_client, tracker, db_conn):
    """채점이 세션 잠금을 먼저 잡으면 종료는 기다렸다가 그 채점을 포함한 점수를 돌려준다."""
    question = pick_question(db_conn)
    question_id, answer = question["id"], question["answer"]
    tracker.snapshot_state(question_id)
    before = counters(tracker.states[question_id])
    session_id = create_session(live_client)
    tracker.track_session(session_id)

    grading: dict = {}
    finishing: dict = {}

    def send_grading() -> None:
        grading["response"] = live_client.post(
            f"/api/questions/{question_id}/answer",
            json={"choiceNo": answer, "sessionId": session_id},
            headers=auth_headers(),
        )

    def send_finish() -> None:
        finishing["response"] = live_client.post(
            f"/api/sessions/{session_id}/finish", headers=auth_headers()
        )

    blocker = lock_connection(autocommit=False)
    probe = lock_connection(autocommit=True)
    grading_thread = threading.Thread(target=send_grading, name="grading")
    finish_thread: threading.Thread | None = None
    try:
        # study_attempt 에 SHARE — 채점의 INSERT(ROW EXCLUSIVE)가 여기서 멈춘다.
        blocker.execute("LOCK TABLE ipe.study_attempt IN SHARE MODE")
        grading_thread.start()
        # 채점이 세션 행 잠금을 잡았는지 확인한다. FOR UPDATE 가 없으면 여기서 시간 초과로 실패한다.
        wait_until(lambda: holds_session_lock(probe, session_id))

        finish_thread = threading.Thread(target=send_finish, name="finish")
        finish_thread.start()
        # 채점이 INSERT 에서 멈춰 있는 동안에는 종료의 UPDATE 도 세션 행 잠금을 기다려야 한다.
        finish_thread.join(timeout=0.3)
        assert finish_thread.is_alive(), "채점 기록이 끝나기 전에 종료가 끝나 버렸다"
    finally:
        blocker.rollback()  # SHARE 해제 — 여기서부터 채점의 INSERT 가 진행된다
        blocker.close()
        probe.close()
        grading_thread.join(timeout=10)
        if finish_thread is not None:
            finish_thread.join(timeout=10)

    assert not grading_thread.is_alive() and "response" in grading, "채점 요청이 끝나지 않았다"
    finish = finishing.get("response")
    assert finish is not None and finish_thread is not None, "종료 요청이 끝나지 않았다"
    grade_response = grading["response"]
    assert grade_response.status_code == 200, grade_response.text
    assert finish.status_code == 200, finish.text
    body = finish.json()
    assert body["finishedAt"] is not None
    assert body["answered"] == 1, "종료가 앞선 채점을 포함하지 않았다"
    assert body["correct"] == 1
    assert get_attempts(db_conn, session_id) == [
        {"choice_no": answer, "is_correct": True, "elapsed_ms": None}
    ]
    state = live_client.get(f"/api/progress/questions/{question_id}").json()
    assert state["attemptCount"] == before["attempt_count"] + 1


def test_grading_started_after_finish_is_rejected_without_writes(live_client, tracker, db_conn):
    """종료가 먼저 끝난 뒤 시작한 채점은 409 이고 study_attempt·study_state 가 늘지 않는다."""
    question = pick_question(db_conn)
    question_id, answer = question["id"], question["answer"]
    wrong_choice = 1 if answer != 1 else 2
    tracker.snapshot_state(question_id)
    before = counters(tracker.states[question_id])
    session_id = create_session(live_client)
    tracker.track_session(session_id)
    post_answer(live_client, question_id, wrong_choice, sessionId=session_id)

    finish = live_client.post(f"/api/sessions/{session_id}/finish", headers=auth_headers())
    assert finish.status_code == 200, finish.text
    assert finish.json()["answered"] == 1

    rejected = live_client.post(
        f"/api/questions/{question_id}/answer",
        json={"choiceNo": answer, "sessionId": session_id},
        headers=auth_headers(),
    )
    assert rejected.status_code == 409, rejected.text
    assert "종료된 세션" in rejected.json()["detail"]

    # 응답 이력은 그대로, 문항 상태 누계도 그대로다(409 는 아무것도 쓰지 않는다).
    assert get_attempts(db_conn, session_id) == [
        {"choice_no": wrong_choice, "is_correct": False, "elapsed_ms": None}
    ]
    state = live_client.get(f"/api/progress/questions/{question_id}").json()
    assert state["attemptCount"] == before["attempt_count"] + 1
    assert state["correctCount"] == before["correct_count"]
    assert state["wrongCount"] == before["wrong_count"] + 1
    assert state["lastIsCorrect"] is False
    assert state["lastChoiceNo"] == wrong_choice
