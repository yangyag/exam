"""실제 PostgreSQL(ipe 스키마)에 붙는 통합 테스트.

- integration 마커로 분리한다. `pytest -m "not integration"` 이면 DB 없이 돈다.
- 채점·진도 기록은 HTTP 를 거치면 롤백할 수 없으므로, 이 모듈이 만든 세션·시도·상태를
  ProgressTracker 가 추적해 **테스트 전 상태로** 되돌린다(모듈 종료 시 검증).
- 접속은 백엔드와 같은 조건(app/db.py 와 같은 search_path=ipe,public)이다.
  접속 정보가 없으면 실패가 아니라 skip 한다.
"""
from __future__ import annotations

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app import cycles
from app import db as app_db
from app.config import get_settings
from app.main import app as fastapi_app
from app.queries import content_key, fetch_content_rows

from helpers import assert_no_answer_leak

pytestmark = pytest.mark.integration

STATE_COLUMNS = (
    "question_id",
    "attempt_count",
    "correct_count",
    "wrong_count",
    "last_is_correct",
    "last_choice_no",
    "last_answered_at",
    "streak",
    "bookmarked",
    "note",
    "review_due_on",
    "updated_at",
)
STATE_RESTORE_SQL = (
    f"INSERT INTO ipe.study_state ({', '.join(STATE_COLUMNS)}) "
    f"VALUES ({', '.join(['%s'] * len(STATE_COLUMNS))})"
)
EMPTY_COUNTERS = {
    "attempt_count": 0,
    "correct_count": 0,
    "wrong_count": 0,
    "streak": 0,
    "last_is_correct": None,
    "last_choice_no": None,
}


def counters(state: dict | None) -> dict:
    """기준 상태(없으면 0)에서 세는 값만 뽑는다."""
    base = dict(EMPTY_COUNTERS)
    if state:
        base.update({key: state[key] for key in EMPTY_COUNTERS})
    return base


class ProgressTracker:
    """테스트가 만든 진도 행을 추적해 테스트 전 상태로 복원한다."""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        self.sessions: list[int] = []
        self.cycles: list[int] = []
        # 문항별 테스트 전 study_state 행(None 이면 원래 없던 문항)
        self.states: dict[str, dict | None] = {}

    def track_session(self, session_id: int) -> None:
        self.sessions.append(session_id)

    def track_cycle(self, cycle_id: int) -> None:
        """사이클은 라운드 전환으로 세션을 더 만들 수 있어 사이클째로 추적한다."""
        self.cycles.append(cycle_id)

    def snapshot_state(self, question_id: str) -> dict | None:
        """문항 상태를 건드리기 전에 원래 값을 기억한다."""
        if question_id not in self.states:
            self.states[question_id] = self.conn.execute(
                "SELECT * FROM ipe.study_state WHERE question_id = %s", (question_id,)
            ).fetchone()
        return self.states[question_id]

    def cleanup(self) -> None:
        if self.cycles:
            # 사이클의 모든 라운드 세션을 먼저 지운다 — 슬롯·원장은 연쇄 삭제된다.
            self.conn.execute(
                "DELETE FROM ipe.study_session WHERE cycle_id = ANY(%s)", (self.cycles,)
            )
            self.conn.execute("DELETE FROM ipe.study_cycle WHERE id = ANY(%s)", (self.cycles,))
        if self.sessions:
            self.conn.execute(
                "DELETE FROM ipe.study_attempt WHERE session_id = ANY(%s)", (self.sessions,)
            )
            self.conn.execute("DELETE FROM ipe.study_session WHERE id = ANY(%s)", (self.sessions,))
        for question_id, before in self.states.items():
            self.conn.execute("DELETE FROM ipe.study_state WHERE question_id = %s", (question_id,))
            if before is not None:
                self.conn.execute(STATE_RESTORE_SQL, tuple(before[column] for column in STATE_COLUMNS))

    def verify_restored(self) -> None:
        """이 테스트가 만든 행이 하나도 남지 않았고, 기존 행은 그대로인지 확인한다."""
        for cycle_id in self.cycles:
            left = self.conn.execute(
                "SELECT count(*)::int AS n FROM ipe.study_session WHERE cycle_id = %s", (cycle_id,)
            ).fetchone()["n"]
            assert left == 0, f"사이클 {cycle_id} 의 세션이 {left}건 남았다"
            assert (
                self.conn.execute("SELECT 1 FROM ipe.study_cycle WHERE id = %s", (cycle_id,)).fetchone()
                is None
            ), f"study_cycle {cycle_id} 가 정리되지 않았다"
        for session_id in self.sessions:
            assert (
                self.conn.execute("SELECT 1 FROM ipe.study_session WHERE id = %s", (session_id,)).fetchone()
                is None
            ), f"study_session {session_id} 가 정리되지 않았다"
            left = self.conn.execute(
                "SELECT count(*)::int AS n FROM ipe.study_attempt WHERE session_id = %s", (session_id,)
            ).fetchone()["n"]
            assert left == 0, f"study_attempt 에 세션 {session_id} 의 행이 {left}건 남았다"
        for question_id, before in self.states.items():
            now = self.conn.execute(
                "SELECT * FROM ipe.study_state WHERE question_id = %s", (question_id,)
            ).fetchone()
            assert now == before, f"{question_id} 의 study_state 가 복원되지 않았다: {before} → {now}"


@pytest.fixture(scope="module")
def db_conn():
    """백엔드와 같은 조건의 직접 커넥션. 접속할 수 없으면 통합 테스트를 건너뛴다."""
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


@pytest.fixture(scope="module")
def tracker(db_conn):
    """진도 행 추적기. 모듈의 모든 테스트가 끝나면 정리하고 복원을 검증한다."""
    progress = ProgressTracker(db_conn)
    yield progress
    progress.cleanup()
    progress.verify_restored()


@pytest.fixture()
def live_client(db_conn, tracker):
    """lifespan(=DB 커넥션 풀)을 실제로 돌리는 TestClient. db_conn 이 접속을 확인한 뒤에만 쓰인다."""
    with TestClient(fastapi_app) as client:
        yield client


def auth_headers() -> dict[str, str]:
    """EXAM_API_TOKEN 이 설정된 환경이면 쓰기 요청에 토큰을 붙인다."""
    token = get_settings().api_token
    return {"X-Exam-Token": token} if token else {}


def pick_question(conn: psycopg.Connection, exclude: set[str] | None = None) -> dict:
    """아직 응답 이력이 없는 문항을 고른다. 전부 이력이 있으면 아무 문항이나."""
    exclude = exclude or set()
    row = conn.execute(
        """SELECT q.id, q.answer, q.exam_id, q.subject_code
             FROM ipe.question q
            WHERE NOT EXISTS (SELECT 1 FROM ipe.study_state s WHERE s.question_id = q.id)
              AND NOT (q.id = ANY(%s))
            ORDER BY q.id
            LIMIT 1""",
        (list(exclude),),
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT id, answer, exam_id, subject_code FROM ipe.question ORDER BY id LIMIT 1"
        ).fetchone()
    return row


def create_session(client: TestClient) -> int:
    response = client.post("/api/sessions", json={"mode": "random"}, headers=auth_headers())
    assert response.status_code == 201, response.text
    return response.json()["id"]


def post_answer(client: TestClient, question_id: str, choice_no: int, **extra) -> dict:
    response = client.post(
        f"/api/questions/{question_id}/answer",
        json={"choiceNo": choice_no, **extra},
        headers=auth_headers(),
    )
    assert response.status_code == 200, response.text
    return response.json()


def get_attempts(conn: psycopg.Connection, session_id: int) -> list[dict]:
    return conn.execute(
        "SELECT choice_no, is_correct, elapsed_ms FROM ipe.study_attempt "
        "WHERE session_id = %s ORDER BY id",
        (session_id,),
    ).fetchall()


def create_slot_session(client: TestClient, mode: str, exam_id: str, **extra) -> int:
    """회차 슬롯 세션(exam_practice·exam)을 만든다. 201 이 아니면 실패시킨다."""
    response = client.post(
        "/api/sessions", json={"mode": mode, "examId": exam_id, **extra}, headers=auth_headers()
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def put_slot(client: TestClient, session_id: int, seq: int, choice_no: int | None, **extra):
    """슬롯 제출 응답을 그대로 돌려준다(200·409 판정은 테스트가 한다)."""
    return client.put(
        f"/api/sessions/{session_id}/items/{seq}/answer",
        json={"choiceNo": choice_no, **extra},
        headers=auth_headers(),
    )


def slot_questions(conn: psycopg.Connection, session_id: int) -> list[dict]:
    """세션 슬롯 + 문항 정답. seq 오름차순."""
    return conn.execute(
        """SELECT si.seq, si.question_id, q.answer, q.subject_code
             FROM ipe.study_session_item si
             JOIN ipe.question q ON q.id = si.question_id
            WHERE si.session_id = %s
            ORDER BY si.seq""",
        (session_id,),
    ).fetchall()


def test_health_reports_database_ok(live_client):
    response = live_client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_question_reads_hide_answer(live_client, db_conn):
    """실제 문항으로 조회·랜덤·목록·통계를 불러도 정답·해설이 응답에 없다."""
    question = pick_question(db_conn)

    single = live_client.get(f"/api/questions/{question['id']}")
    assert single.status_code == 200
    assert single.json()["id"] == question["id"]
    assert_no_answer_leak(single.json())

    random_items = live_client.get("/api/questions/random", params={"count": 5})
    assert random_items.status_code == 200
    assert 0 < len(random_items.json()) <= 5
    for item in random_items.json():
        assert_no_answer_leak(item)

    page = live_client.get(f"/api/exams/{question['exam_id']}/questions", params={"limit": 5})
    assert page.status_code == 200
    assert page.json()["total"] >= len(page.json()["items"])
    for item in page.json()["items"]:
        assert_no_answer_leak(item)

    # 통계·메타 응답도 마찬가지(뷰에 q.answer 가 있어도 API 는 싣지 않는다).
    for path, params in (
        ("/api/stats/wrong-questions", {"limit": 200}),
        ("/api/stats/review-due", {"limit": 200}),
        ("/api/stats/subjects", {}),
        ("/api/progress/questions", {"limit": 200}),
        ("/api/tags", {"limit": 100}),
        ("/api/exams", {}),
        ("/api/subjects", {}),
    ):
        response = live_client.get(path, params=params)
        assert response.status_code == 200, f"{path} → {response.status_code}"
        assert_no_answer_leak(response.json())


def test_grading_wrong_then_correct_updates_state_and_history(live_client, tracker, db_conn):
    """오답 → 정답 순서로 채점하며 study_state 누계와 study_attempt 이력을 확인한다."""
    question = pick_question(db_conn)
    question_id, answer = question["id"], question["answer"]
    wrong_choice = 1 if answer != 1 else 2

    tracker.snapshot_state(question_id)
    before = counters(tracker.states[question_id])
    session_id = create_session(live_client)
    tracker.track_session(session_id)

    wrong = post_answer(live_client, question_id, wrong_choice, sessionId=session_id, elapsedMs=1500)
    assert wrong["isCorrect"] is False
    assert wrong["answer"] == answer
    assert wrong["explanation"]
    assert [item["no"] for item in wrong["choicesAnalysis"] if item["correct"]] == [answer]
    assert wrong["state"]["attemptCount"] == before["attempt_count"] + 1
    assert wrong["state"]["correctCount"] == before["correct_count"]
    assert wrong["state"]["wrongCount"] == before["wrong_count"] + 1
    assert wrong["state"]["lastIsCorrect"] is False
    assert wrong["state"]["lastChoiceNo"] == wrong_choice

    attempts = get_attempts(db_conn, session_id)
    assert attempts == [{"choice_no": wrong_choice, "is_correct": False, "elapsed_ms": 1500}]

    correct = post_answer(live_client, question_id, answer, sessionId=session_id)
    assert correct["isCorrect"] is True
    assert correct["answer"] == answer
    assert correct["state"]["attemptCount"] == before["attempt_count"] + 2
    assert correct["state"]["correctCount"] == before["correct_count"] + 1
    assert correct["state"]["wrongCount"] == before["wrong_count"] + 1
    assert correct["state"]["lastIsCorrect"] is True
    assert correct["state"]["lastChoiceNo"] == answer
    assert correct["state"]["streak"] == 1

    # study_attempt 는 append-only 이력이라 두 번의 응답이 그대로 남는다.
    attempts = get_attempts(db_conn, session_id)
    assert [(row["choice_no"], row["is_correct"], row["elapsed_ms"]) for row in attempts] == [
        (wrong_choice, False, 1500),
        (answer, True, None),
    ]

    # HTTP 조회로도 같은 상태가 보인다.
    progress = live_client.get(f"/api/progress/questions/{question_id}")
    assert progress.status_code == 200
    assert progress.json()["attemptCount"] == before["attempt_count"] + 2
    assert progress.json()["lastChoiceNo"] == answer

    finish = live_client.post(f"/api/sessions/{session_id}/finish", headers=auth_headers())
    assert finish.status_code == 200
    assert finish.json()["finishedAt"] is not None
    assert finish.json()["answered"] == 2
    assert finish.json()["correct"] == 1

    sessions = live_client.get("/api/sessions", params={"limit": 50}).json()
    mine = [item for item in sessions if item["id"] == session_id]
    assert mine, "방금 만든 세션이 목록에 없다"
    assert mine[0]["answered"] == 2
    assert mine[0]["correct"] == 1


def test_progress_patch_and_stats(live_client, tracker, db_conn):
    """북마크·메모·복습 예정일을 저장하고 통계(오답·복습·과목)에 반영되는지 본다."""
    taken = set(tracker.states)
    question = pick_question(db_conn, exclude=taken)
    question_id, answer = question["id"], question["answer"]
    wrong_choice = 1 if answer != 1 else 2

    tracker.snapshot_state(question_id)
    session_id = create_session(live_client)
    tracker.track_session(session_id)
    post_answer(live_client, question_id, wrong_choice, sessionId=session_id)

    # 복습 뷰의 '오늘'은 DB 시간대(UTC)의 current_date 이거나 Asia/Seoul 기준일 수 있다.
    # 자정 근처에서 두 날짜가 하루 달라지므로 이른 쪽으로 예약하고 지연 일수는 0~1 로 본다.
    today = db_conn.execute(
        "SELECT least(current_date, (now() AT TIME ZONE 'Asia/Seoul')::date) AS d"
    ).fetchone()["d"]
    patch = live_client.patch(
        f"/api/progress/questions/{question_id}",
        json={"bookmarked": True, "note": "통합 테스트 메모", "reviewDueOn": today.isoformat()},
        headers=auth_headers(),
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["bookmarked"] is True
    assert patch.json()["note"] == "통합 테스트 메모"
    assert patch.json()["reviewDueOn"] == today.isoformat()

    stored = db_conn.execute(
        "SELECT bookmarked, note, review_due_on FROM ipe.study_state WHERE question_id = %s",
        (question_id,),
    ).fetchone()
    assert stored == {"bookmarked": True, "note": "통합 테스트 메모", "review_due_on": today}

    listed = live_client.get(
        "/api/progress/questions", params={"bookmarked": "true", "wrong": "true", "limit": 200}
    ).json()
    assert question_id in [item["questionId"] for item in listed]

    wrong_items = live_client.get("/api/stats/wrong-questions", params={"limit": 200}).json()
    mine = [item for item in wrong_items if item["questionId"] == question_id]
    assert mine, "방금 틀린 문항이 오답 목록에 없다"
    assert mine[0]["wrongCount"] >= 1
    assert_no_answer_leak(mine[0])

    due_items = live_client.get("/api/stats/review-due", params={"limit": 200}).json()
    due = [item for item in due_items if item["questionId"] == question_id]
    assert due, "복습 예정일이 오늘인 문항이 복습 목록에 없다"
    assert due[0]["overdueDays"] in (0, 1)
    assert_no_answer_leak(due[0])

    subject_stats = live_client.get("/api/stats/subjects").json()
    subject = [item for item in subject_stats if item["subjectCode"] == question["subject_code"]]
    assert subject, "과목 통계에 해당 과목 행이 없다"
    assert subject[0]["answered"] >= 1
    assert subject[0]["accuracyPct"] is not None


def test_progress_filters_both_directions_on_live_data(live_client, tracker, db_conn):
    """`wrong`·`unresolved` 의 true/false 양방향을 실제 데이터로 고정한다.

    응답 이력 없이 북마크만 남긴 행(`wrong_count` 0 · `last_is_correct` NULL)이
    `unresolved=false` 에서 빠지지 않는지, 틀렸다가 맞춘 문항은 `unresolved=false` 로,
    아직 못 푼 오답은 `unresolved=true` 로 나오는지 확인한다.
    """
    picked: list[dict] = []
    for _ in range(3):
        picked.append(pick_question(db_conn, exclude={q["id"] for q in picked}))
    assert len({q["id"] for q in picked}) == 3, "서로 다른 문항 3개를 고르지 못했다"
    bookmark_only, resolved, unresolved = picked

    session_id = create_session(live_client)
    tracker.track_session(session_id)
    for question in picked:
        tracker.snapshot_state(question["id"])
        response = live_client.patch(
            f"/api/progress/questions/{question['id']}",
            json={"bookmarked": True},
            headers=auth_headers(),
        )
        assert response.status_code == 200, response.text

    def answer_wrong(question: dict) -> None:
        post_answer(live_client, question["id"], 1 if question["answer"] != 1 else 2, sessionId=session_id)

    answer_wrong(unresolved)
    answer_wrong(resolved)
    post_answer(live_client, resolved["id"], resolved["answer"], sessionId=session_id)

    stored = db_conn.execute(
        "SELECT wrong_count, last_is_correct FROM ipe.study_state WHERE question_id = %s",
        (bookmark_only["id"],),
    ).fetchone()
    assert stored == {"wrong_count": 0, "last_is_correct": None}, f"NULL 케이스가 아니다: {stored}"

    def listed(**flags: str) -> set[str]:
        response = live_client.get(
            "/api/progress/questions", params={"bookmarked": "true", "limit": 200, **flags}
        )
        assert response.status_code == 200, response.text
        return {item["questionId"] for item in response.json()}

    # wrong=false = 한 번도 틀린 적 없음. NULL(last_is_correct) 행은 wrong_count 0 이라 여기 들어온다.
    never_wrong = listed(wrong="false")
    assert bookmark_only["id"] in never_wrong
    assert resolved["id"] not in never_wrong, "한 번 틀린 문항이 wrong=false 에 나왔다"
    assert unresolved["id"] not in never_wrong

    # wrong=true = 한 번이라도 틀림.
    ever_wrong = listed(wrong="true")
    assert resolved["id"] in ever_wrong
    assert unresolved["id"] in ever_wrong
    assert bookmark_only["id"] not in ever_wrong

    # unresolved=false = 마지막이 맞았거나 틀린 적 없음(NULL 을 FALSE 로 보지 않는다).
    settled = listed(unresolved="false")
    assert bookmark_only["id"] in settled, "last_is_correct NULL 행이 unresolved=false 에서 빠졌다"
    assert resolved["id"] in settled, "틀렸다가 맞춘 문항이 unresolved=false 에서 빠졌다"
    assert unresolved["id"] not in settled

    # unresolved=true = 마지막 응답도 틀림.
    still_wrong = listed(unresolved="true")
    assert unresolved["id"] in still_wrong
    assert resolved["id"] not in still_wrong
    assert bookmark_only["id"] not in still_wrong


def test_finished_session_rejects_grading_and_keeps_state_accumulating(live_client, tracker, db_conn):
    """제출한 세션은 채점을 거부(409)하고 요약이 고정된다. 문항별 누계는 다른 세션으로 계속 쌓인다."""
    question = pick_question(db_conn)
    question_id, answer = question["id"], question["answer"]
    wrong_choice = 1 if answer != 1 else 2

    tracker.snapshot_state(question_id)
    before = counters(tracker.states[question_id])

    submitted = create_session(live_client)
    tracker.track_session(submitted)
    post_answer(live_client, question_id, wrong_choice, sessionId=submitted)
    finish = live_client.post(f"/api/sessions/{submitted}/finish", headers=auth_headers())
    assert finish.status_code == 200, finish.text
    assert finish.json()["finishedAt"] is not None
    assert finish.json()["answered"] == 1
    assert finish.json()["correct"] == 0

    # 제출한 세션으로 다시 채점하면 409 — study_attempt 도 study_state 도 늘지 않는다.
    rejected = live_client.post(
        f"/api/questions/{question_id}/answer",
        json={"choiceNo": answer, "sessionId": submitted},
        headers=auth_headers(),
    )
    assert rejected.status_code == 409, rejected.text
    assert "종료된 세션" in rejected.json()["detail"]
    assert get_attempts(db_conn, submitted) == [
        {"choice_no": wrong_choice, "is_correct": False, "elapsed_ms": None}
    ]
    state = live_client.get(f"/api/progress/questions/{question_id}").json()
    assert state["attemptCount"] == before["attempt_count"] + 1
    assert state["correctCount"] == before["correct_count"]

    def submitted_summary() -> dict:
        """세션 목록에서 제출한 세션의 요약(answered·correct)만 뽑는다."""
        sessions = live_client.get("/api/sessions", params={"limit": 50}).json()
        mine = [item for item in sessions if item["id"] == submitted]
        assert mine, "방금 만든 세션이 목록에 없다"
        return mine[0]

    summary = submitted_summary()
    assert summary["answered"] == 1 and summary["correct"] == 0

    # 계속 풀려면 새 세션 — 문항별 누계는 새 세션의 채점으로 계속 갱신된다.
    resumed = create_session(live_client)
    tracker.track_session(resumed)
    correct = post_answer(live_client, question_id, answer, sessionId=resumed)
    assert correct["state"]["attemptCount"] == before["attempt_count"] + 2
    assert correct["state"]["correctCount"] == before["correct_count"] + 1
    assert correct["state"]["lastIsCorrect"] is True

    # 종료된 세션의 요약은 새 세션의 채점으로도 변하지 않는다.
    assert submitted_summary()["answered"] == 1
    assert submitted_summary()["correct"] == 0


def _content_key_of(item: dict) -> str:
    """조회 응답(QuestionOut)에서 중복 판정 키를 만든다. DB 행과 같은 규칙을 쓴다."""
    return content_key(
        {
            "stem": item["stem"],
            "passage": item["passage"],
            "passage_kind": item["passageKind"],
            "figure_needed": item["figure"]["needed"],
            "figure_kind": item["figure"]["kind"],
            "figure_alt": item["figure"]["alt"],
            "choice_texts": [choice["text"] for choice in item["choices"]],
        }
    )


def test_random_returns_one_question_per_content_group(live_client, db_conn):
    """2023-1-001 과 2023-1-023(보기 2의 자연어 쉼표 차이)은 같은 그룹이라 한 응답에 함께 나오지 않는다.

    2023-1 은 100문항이되 고유 그룹이 99개다(001·023 이 한 그룹) — count=100 이면 99개만 나온다.
    중복을 제거한 고유 그룹이 count 보다 적으면 가용한 만큼만 돌려준다(부족분 허용).
    """
    first = live_client.get("/api/questions/2023-1-001")
    duplicate = live_client.get("/api/questions/2023-1-023")
    assert first.status_code == 200 and duplicate.status_code == 200
    assert first.json()["stem"] == duplicate.json()["stem"]
    assert _content_key_of(first.json()) == _content_key_of(duplicate.json()), "같은 내용이 다른 키다"

    rows = fetch_content_rows(db_conn, where="q.exam_id = %s", params=["2023-1"])
    assert len(rows) == 100, "2023-1 회차 문항 수가 바뀌었다"
    unique_groups = len({content_key(row) for row in rows})
    assert unique_groups == 99, "2023-1 의 고유 그룹이 99개가 아니다(중복·키 규칙이 바뀌었는지 확인)"

    response = live_client.get("/api/questions/random", params={"examId": "2023-1", "count": 100})
    assert response.status_code == 200
    items = response.json()
    ids = [item["id"] for item in items]
    assert len(ids) == 99, "중복 제거 결과가 99개가 아니다"
    assert len(ids) == unique_groups, "고유 그룹 수만큼 돌려주지 않았다"
    assert sum(item_id in ids for item_id in ("2023-1-001", "2023-1-023")) == 1
    assert len({_content_key_of(item) for item in items}) == len(items), "같은 내용이 두 번 나왔다"


def test_content_key_keeps_similar_questions_apart(live_client):
    """stem 이 겹치는 문항이라도 지문·보기·도식이 다르면 다른 그룹이다(과병합 방지)."""

    def fetch(question_id: str) -> dict:
        response = live_client.get(f"/api/questions/{question_id}")
        assert response.status_code == 200, response.text
        return response.json()

    # 같은 stem + 같은 보기 + 다른 지문(표를 공백으로 복원한 회차와 ' | ' 로 복원한 회차)
    space_table, piped_table = fetch("2022-2-022"), fetch("2023-3-039")
    assert space_table["stem"] == piped_table["stem"]
    assert [c["text"] for c in space_table["choices"]] == [c["text"] for c in piped_table["choices"]]
    assert _content_key_of(space_table) != _content_key_of(piped_table)

    # 같은 stem + 같은 지문 + 다른 보기(∥ 와 || — 기호를 지우면 합쳐질 수 있는 쌍)
    parallel_a, parallel_b = fetch("2022-1-064"), fetch("2023-2-075")
    assert parallel_a["stem"] == parallel_b["stem"]
    assert parallel_a["passage"] == parallel_b["passage"]
    assert _content_key_of(parallel_a) != _content_key_of(parallel_b)

    # 같은 stem·지문·보기 + 다른 도식(설명 alt 가 다르다)
    figure_a, figure_b = fetch("2022-3-017"), fetch("2023-3-008")
    assert figure_a["stem"] == figure_b["stem"]
    assert figure_a["passage"] == figure_b["passage"]
    assert [c["text"] for c in figure_a["choices"]] == [c["text"] for c in figure_b["choices"]]
    assert _content_key_of(figure_a) != _content_key_of(figure_b)


def test_create_session_with_blank_exam_id_stores_null(live_client, tracker, db_conn):
    """빈 문자열 examId 는 null 로 정규화되어 외래 키 위반(500) 없이 만들어진다(B-02)."""
    created = live_client.post(
        "/api/sessions", json={"mode": "random", "examId": ""}, headers=auth_headers()
    )
    assert created.status_code == 201, created.text
    body = created.json()
    tracker.track_session(body["id"])
    assert body["examId"] is None
    stored = db_conn.execute(
        "SELECT exam_id FROM ipe.study_session WHERE id = %s", (body["id"],)
    ).fetchone()
    assert stored == {"exam_id": None}

    # mode=exam 에서는 빈 문자열이 null 이 되어 기존 400(examId 필요)으로 간다.
    refused = live_client.post(
        "/api/sessions", json={"mode": "exam", "examId": ""}, headers=auth_headers()
    )
    assert refused.status_code == 400, refused.text


def _exam_with_questions(conn: psycopg.Connection, exclude: set[str] | None = None) -> str:
    """문항이 있는 회차 하나. 다른 테스트와 겹치지 않게 exclude 로 뺄 수 있다."""
    exclude = exclude or set()
    row = conn.execute(
        """SELECT e.id FROM ipe.exam e
            WHERE EXISTS (SELECT 1 FROM ipe.question q WHERE q.exam_id = e.id)
              AND NOT (e.id = ANY(%s))
            ORDER BY e.id LIMIT 1""",
        (list(exclude),),
    ).fetchone()
    assert row is not None, "테스트에 쓸 회차가 없다"
    return row["id"]


def test_exam_practice_slots_resume_and_grade(live_client, tracker, db_conn):
    """회차 연습: 번호 순 슬롯 생성 → 이어풀기(nextSeq) → 재전송 멱등 → 다른 보기 409.

    채점 전 state 비노출과 조회가 원장을 늘리지 않는 것도 실제 DB 로 고정한다.
    """
    exam_id = _exam_with_questions(db_conn)
    session_id = create_slot_session(live_client, "exam_practice", exam_id)
    tracker.track_session(session_id)

    detail = live_client.get(f"/api/sessions/{session_id}").json()
    assert detail["mode"] == "exam_practice"
    assert detail["itemCount"] == 100
    assert detail["answeredCount"] == 0
    assert detail["nextSeq"] == 1
    assert [item["seq"] for item in detail["items"]] == list(range(1, 101))
    assert detail["items"][0]["choiceNo"] is None
    assert detail["items"][0]["isCorrect"] is None

    # 회차 문항 번호 순 — 첫 슬롯이 1번 문항이다.
    number = db_conn.execute(
        "SELECT number FROM ipe.question WHERE id = %s", (detail["items"][0]["questionId"],)
    ).fetchone()["number"]
    assert number == 1

    # 채점 전 문항 조회: state 비노출·result 없음·원장 무기록
    item = live_client.get(f"/api/sessions/{session_id}/items/1")
    assert item.status_code == 200
    item_body = item.json()
    assert item_body["state"] is None
    assert item_body["result"] is None
    assert_no_answer_leak(item_body)
    assert get_attempts(db_conn, session_id) == []

    question = db_conn.execute(
        "SELECT id, answer FROM ipe.question WHERE id = %s", (detail["items"][0]["questionId"],)
    ).fetchone()
    question_id, answer = question["id"], question["answer"]
    wrong_choice = 1 if answer != 1 else 2
    tracker.snapshot_state(question_id)

    graded = put_slot(live_client, session_id, 1, wrong_choice)
    assert graded.status_code == 200, graded.text
    graded_body = graded.json()
    assert graded_body["isCorrect"] is False
    assert graded_body["answer"] == answer
    assert graded_body["session"]["answeredCount"] == 1
    assert graded_body["session"]["nextSeq"] == 2
    assert graded_body["roundResult"] is None
    assert graded_body["cycle"] is None
    assert len(get_attempts(db_conn, session_id)) == 1

    # 같은 보기 재전송: 기록 없이 200
    again = put_slot(live_client, session_id, 1, wrong_choice)
    assert again.status_code == 200, again.text
    assert again.json()["isCorrect"] is False
    assert len(get_attempts(db_conn, session_id)) == 1

    # 다른 보기: 409, 기록 그대로
    conflict = put_slot(live_client, session_id, 1, answer)
    assert conflict.status_code == 409
    assert "이미 채점된" in conflict.json()["detail"]
    assert len(get_attempts(db_conn, session_id)) == 1

    # 채점된 슬롯 조회: result 에 정답·해설, 전후로 원장은 그대로다.
    graded_item = live_client.get(f"/api/sessions/{session_id}/items/1").json()
    assert graded_item["result"]["answer"] == answer
    assert graded_item["result"]["explanation"]
    assert graded_item["state"] is None
    live_client.get(f"/api/sessions/{session_id}")
    assert len(get_attempts(db_conn, session_id)) == 1

    # 진도 요약에 슬롯 필드가 실린다.
    sessions = live_client.get("/api/sessions", params={"mode": "exam_practice", "limit": 50}).json()
    mine = [row for row in sessions if row["id"] == session_id][0]
    assert mine["cycleId"] is None and mine["roundNo"] is None and mine["endReason"] is None
    assert mine["answered"] == 1


def test_exam_session_selection_and_replace_active(live_client, tracker, db_conn):
    """모의고사: 선택 저장(정답 비공개)·선택 해제·진행 중 409·replaceActive 새로 구성을 고정한다."""
    exam_id = _exam_with_questions(db_conn, exclude={"2026-1"})
    first = create_slot_session(live_client, "exam", exam_id)
    tracker.track_session(first)

    # 진행 중인데 한 번 더 만들면 409
    conflict = live_client.post(
        "/api/sessions", json={"mode": "exam", "examId": exam_id}, headers=auth_headers()
    )
    assert conflict.status_code == 409

    slot = live_client.get(f"/api/sessions/{first}").json()["items"][0]
    question = db_conn.execute(
        "SELECT id, answer FROM ipe.question WHERE id = %s", (slot["questionId"],)
    ).fetchone()
    tracker.snapshot_state(question["id"])
    assert get_attempts(db_conn, first) == []

    # 선택 저장: 정답 없이 저장되고 원장·누계는 그대로다.
    saved = put_slot(live_client, first, 1, 2)
    assert saved.status_code == 200, saved.text
    assert saved.json()["choiceNo"] == 2
    assert "answer" not in saved.json()
    assert get_attempts(db_conn, first) == []
    stored = db_conn.execute(
        "SELECT choice_no, is_correct FROM ipe.study_session_item WHERE session_id = %s AND seq = 1",
        (first,),
    ).fetchone()
    assert stored == {"choice_no": 2, "is_correct": None}

    # 진행 중 모의고사는 슬롯 목록·문항 조회에서 정답을 가리고, nextSeq 는 선택 없는 슬롯이다.
    detail = live_client.get(f"/api/sessions/{first}").json()
    assert detail["items"][0]["choiceNo"] == 2
    assert detail["items"][0]["isCorrect"] is None
    assert detail["nextSeq"] == 2
    item = live_client.get(f"/api/sessions/{first}/items/1").json()
    assert item["result"] is None
    assert item["state"] is None
    assert_no_answer_leak(item)

    # 선택 해제(choiceNo=null)와 답안 수정
    assert put_slot(live_client, first, 1, 3).json()["choiceNo"] == 3
    cleared = put_slot(live_client, first, 1, None)
    assert cleared.status_code == 200
    assert cleared.json()["choiceNo"] is None
    assert live_client.get(f"/api/sessions/{first}").json()["nextSeq"] == 1

    # 새로 구성: 기존 세션은 abandoned 로 보존, 새 세션이 열린다.
    replaced = live_client.post(
        "/api/sessions",
        json={"mode": "exam", "examId": exam_id, "replaceActive": True},
        headers=auth_headers(),
    )
    assert replaced.status_code == 201, replaced.text
    second = replaced.json()["id"]
    tracker.track_session(second)
    old = db_conn.execute(
        "SELECT finished_at, end_reason FROM ipe.study_session WHERE id = %s", (first,)
    ).fetchone()
    assert old["finished_at"] is not None and old["end_reason"] == "abandoned"

    # 중단된 세션에 슬롯 제출하면 409 — '이미 제출'(사실과 다름)이 아니라 중단 안내가 나간다.
    rejected = put_slot(live_client, first, 1, 2)
    assert rejected.status_code == 409
    detail = rejected.json()["detail"]
    assert "중단" in detail
    assert "이미 제출" not in detail
    assert len(get_attempts(db_conn, first)) == 0


def test_last_slot_finishes_exam_practice_session(live_client, tracker, db_conn):
    """연습 마지막 슬롯을 채점하면 세션이 자동 종료되고, 그 뒤 재전송은 409 가 아니라 200 이다."""
    picked = db_conn.execute("SELECT id, answer FROM ipe.question ORDER BY id LIMIT 2").fetchall()
    for row in picked:
        tracker.snapshot_state(row["id"])
    session_id = cycles.create_round_session(
        db_conn, mode="exam_practice", question_ids=[row["id"] for row in picked]
    )
    tracker.track_session(session_id)

    first = put_slot(live_client, session_id, 1, picked[0]["answer"])
    assert first.status_code == 200, first.text
    assert first.json()["session"]["finished"] is False
    assert first.json()["roundResult"] is None

    last = put_slot(live_client, session_id, 2, picked[1]["answer"])
    assert last.status_code == 200, last.text
    body = last.json()
    assert body["session"]["finished"] is True
    assert body["session"]["nextSeq"] is None
    assert body["roundResult"] == {"roundNo": None, "itemCount": 2, "correct": 2, "wrong": 0}
    assert body["cycle"] is None

    # 종료 뒤 마지막 슬롯 재전송: 네트워크 재시도가 409 로 새지 않는다.
    retry = put_slot(live_client, session_id, 2, picked[1]["answer"])
    assert retry.status_code == 200, retry.text
    assert retry.json()["roundResult"] == body["roundResult"]
    assert len(get_attempts(db_conn, session_id)) == 2

    detail = live_client.get(f"/api/sessions/{session_id}").json()
    assert detail["finishedAt"] is not None and detail["endReason"] == "finished"
    assert detail["answeredCount"] == 2
    assert detail["nextSeq"] is None


def test_subject_cycle_round_advances_to_review_and_completes(live_client, tracker, db_conn):
    """과목 사이클: 마지막 슬롯 채점이 라운드를 닫고 review 라운드/완료로 넘어간다(설계 4.5절)."""
    picked = db_conn.execute(
        "SELECT id, answer, subject_code FROM ipe.question WHERE subject_code = 2 ORDER BY id LIMIT 3"
    ).fetchall()
    subject_code = picked[0]["subject_code"]
    for row in picked:
        tracker.snapshot_state(row["id"])

    cycle_id = db_conn.execute(
        "INSERT INTO ipe.study_cycle (subject_code) VALUES (%s) RETURNING id", (subject_code,)
    ).fetchone()["id"]
    tracker.track_cycle(cycle_id)
    round1_id = cycles.create_round_session(
        db_conn,
        mode="subject",
        question_ids=[row["id"] for row in picked],
        subject_code=subject_code,
        cycle_id=cycle_id,
        round_no=1,
    )
    tracker.track_session(round1_id)

    def wrong(row: dict) -> int:
        return 1 if row["answer"] != 1 else 2

    # 1라운드: 첫 문항 정답, 나머지 오답 → 라운드 종료 + review 라운드 생성
    first = put_slot(live_client, round1_id, 1, picked[0]["answer"])
    assert first.status_code == 200, first.text
    assert first.json()["cycle"]["status"] == "active"
    assert first.json()["roundResult"] is None
    assert put_slot(live_client, round1_id, 2, wrong(picked[1])).status_code == 200

    last = put_slot(live_client, round1_id, 3, wrong(picked[2]))
    assert last.status_code == 200, last.text
    body = last.json()
    assert body["session"]["finished"] is True
    assert body["roundResult"] == {"roundNo": 1, "itemCount": 3, "correct": 1, "wrong": 2}
    assert body["cycle"]["status"] == "active"
    assert body["cycle"]["nextRoundNo"] == 2
    assert body["cycle"]["nextItemCount"] == 2
    review_id = body["cycle"]["nextSessionId"]
    assert review_id is not None and review_id != round1_id

    # 라운드 1은 finished 로 닫히고, review 라운드는 오답 문항만 담는다.
    closed = db_conn.execute(
        "SELECT finished_at, end_reason FROM ipe.study_session WHERE id = %s", (round1_id,)
    ).fetchone()
    assert closed["finished_at"] is not None and closed["end_reason"] == "finished"
    review = db_conn.execute(
        "SELECT mode, round_no, cycle_id, subject_code FROM ipe.study_session WHERE id = %s",
        (review_id,),
    ).fetchone()
    assert review == {
        "mode": "review",
        "round_no": 2,
        "cycle_id": cycle_id,
        "subject_code": subject_code,
    }
    review_slots = slot_questions(db_conn, review_id)
    assert sorted(row["question_id"] for row in review_slots) == sorted(
        [picked[1]["id"], picked[2]["id"]]
    )

    # 2라운드: 하나 틀리면 3라운드가 생긴다.
    assert put_slot(live_client, review_id, review_slots[0]["seq"], wrong(review_slots[0])).status_code == 200
    second = put_slot(live_client, review_id, review_slots[1]["seq"], review_slots[1]["answer"])
    assert second.status_code == 200, second.text
    body2 = second.json()
    assert body2["roundResult"] == {"roundNo": 2, "itemCount": 2, "correct": 1, "wrong": 1}
    assert body2["cycle"]["nextRoundNo"] == 3
    assert body2["cycle"]["nextItemCount"] == 1
    round3_id = body2["cycle"]["nextSessionId"]
    assert round3_id is not None

    # 3라운드: 남은 한 문항을 맞히면 사이클이 완료된다.
    round3_slots = slot_questions(db_conn, round3_id)
    assert len(round3_slots) == 1
    final = put_slot(live_client, round3_id, round3_slots[0]["seq"], round3_slots[0]["answer"])
    assert final.status_code == 200, final.text
    body3 = final.json()
    assert body3["roundResult"] == {"roundNo": 3, "itemCount": 1, "correct": 1, "wrong": 0}
    assert body3["cycle"]["status"] == "completed"
    assert body3["cycle"]["nextSessionId"] is None

    # 중간 상태 없음: 완료된 사이클에는 열린 라운드가 없고 ended_at 이 채워져 있다.
    cycle_row = db_conn.execute(
        "SELECT status, ended_at FROM ipe.study_cycle WHERE id = %s", (cycle_id,)
    ).fetchone()
    assert cycle_row["status"] == "completed" and cycle_row["ended_at"] is not None
    open_rounds = db_conn.execute(
        "SELECT count(*)::int AS n FROM ipe.study_session WHERE cycle_id = %s AND finished_at IS NULL",
        (cycle_id,),
    ).fetchone()["n"]
    assert open_rounds == 0


def _start_cycle_with_round(db_conn: psycopg.Connection, tracker: ProgressTracker, subject_code: int):
    """과목의 진행 중 사이클 1개 + 라운드 1 세션 1개를 만든다(테스트 준비용)."""
    question = db_conn.execute(
        "SELECT id FROM ipe.question WHERE subject_code = %s ORDER BY id LIMIT 1", (subject_code,)
    ).fetchone()
    cycle_id = db_conn.execute(
        "INSERT INTO ipe.study_cycle (subject_code) VALUES (%s) RETURNING id", (subject_code,)
    ).fetchone()["id"]
    tracker.track_cycle(cycle_id)
    session_id = cycles.create_round_session(
        db_conn,
        mode="subject",
        question_ids=[question["id"]],
        subject_code=subject_code,
        cycle_id=cycle_id,
        round_no=1,
    )
    tracker.track_session(session_id)
    return cycle_id, session_id


def test_replace_active_cycle_abandons_cycle_and_open_round(tracker, db_conn):
    """새로 구성 헬퍼: 열린 라운드와 사이클을 함께 abandoned 로 닫고, 없으면 null 을 돌려준다."""
    cycle_id, session_id = _start_cycle_with_round(db_conn, tracker, subject_code=3)

    # replaceActive=false 는 409 이고 아무것도 바꾸지 않는다.
    with pytest.raises(HTTPException) as excinfo:
        cycles.replace_active_cycle(db_conn, subject_code=3, replace_active=False)
    assert excinfo.value.status_code == 409
    assert db_conn.execute(
        "SELECT status FROM ipe.study_cycle WHERE id = %s", (cycle_id,)
    ).fetchone()["status"] == "active"

    # replaceActive=true 는 세션(먼저)과 사이클을 함께 중단한다.
    closed = cycles.replace_active_cycle(db_conn, subject_code=3, replace_active=True)
    assert closed is not None
    assert closed["id"] == cycle_id and closed["subject_code"] == 3
    assert closed["status"] == "abandoned" and closed["ended_at"] is not None
    session_state = db_conn.execute(
        "SELECT finished_at, end_reason FROM ipe.study_session WHERE id = %s", (session_id,)
    ).fetchone()
    assert session_state["finished_at"] is not None
    assert session_state["end_reason"] == "abandoned"
    cycle_state = db_conn.execute(
        "SELECT status, ended_at FROM ipe.study_cycle WHERE id = %s", (cycle_id,)
    ).fetchone()
    assert cycle_state["status"] == "abandoned" and cycle_state["ended_at"] is not None

    # 진행 중 사이클이 없으면 아무것도 하지 않고 null.
    assert cycles.replace_active_cycle(db_conn, subject_code=3, replace_active=True) is None


def test_replace_active_cycle_does_not_commit(tracker, db_conn):
    """헬퍼는 호출자의 트랜잭션 안에서만 동작한다 — 롤백하면 중단 전 상태로 돌아온다(M2 계약)."""
    cycle_id, session_id = _start_cycle_with_round(db_conn, tracker, subject_code=4)

    class Rollback(Exception):
        pass

    try:
        with db_conn.transaction():
            closed = cycles.replace_active_cycle(db_conn, subject_code=4, replace_active=True)
            assert closed["status"] == "abandoned"
            # 트랜잭션 안에서는 이미 중단된 것으로 보인다(중간에 커밋하지 않는다).
            inside = db_conn.execute(
                "SELECT status FROM ipe.study_cycle WHERE id = %s", (cycle_id,)
            ).fetchone()
            assert inside["status"] == "abandoned"
            raise Rollback
    except Rollback:
        pass

    # 롤백 뒤 원래대로 — 헬퍼가 스스로 커밋하지 않았다는 증거다.
    assert db_conn.execute(
        "SELECT status FROM ipe.study_cycle WHERE id = %s", (cycle_id,)
    ).fetchone()["status"] == "active"
    assert db_conn.execute(
        "SELECT finished_at FROM ipe.study_session WHERE id = %s", (session_id,)
    ).fetchone()["finished_at"] is None
