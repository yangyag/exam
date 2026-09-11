"""실제 PostgreSQL 에서 과목 사이클 API 의 라운드 전환·동시성을 고정한다(설계 4.5~4.6·5.1~5.2절).

- 홈 요약의 고유 문항 수(176·194·194·199·181)는 API 의 `content_key` 기준 값이다
  (`tools/dups.py` 기준 847 과 다른 수치라 여기서 실제 DB 로 검산한다).
- 과목당 진행 중 1개·두 기기 동시 시작·마지막 문항 제출과 새로 구성의 경합은 가짜 DB 로
  검출할 수 없어 실제 행 잠금으로 재현한다.
- 테스트가 만든 사이클·세션·슬롯·원장·상태 행은 끝나면 되돌린다(ProgressTracker).
"""
from __future__ import annotations

import threading
import time

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app import cycles
from app import db as app_db
from app import queries
from app.config import get_settings
from app.main import app as fastapi_app

from test_integration_db import ProgressTracker, auth_headers, put_slot, slot_questions

pytestmark = pytest.mark.integration

# API(content_key) 기준 과목별 고유 문항 수. 미션·설계 2.3절의 확정 값이다.
UNIQUE_QUESTION_COUNTS = {1: 176, 2: 194, 3: 194, 4: 199, 5: 181}

# 새로 구성(replaceActive)의 2단계 "열린 라운드 잠금" 이 대기 중인지 찾는 조회(설계 4.6절).
# pg_stat_activity.query 는 문장 원문(줄바꿈·바인딩 자리표시자 포함)이라 조각으로 판정한다.
# NOWAIT 프로브는 기다리지 않으므로 여기에 걸리지 않는다.
REPLACE_STEP2_WAITING_SQL = """
SELECT count(*)::int AS n
  FROM pg_stat_activity
 WHERE datname = current_database()
   AND state = 'active'
   AND wait_event_type = 'Lock'
   AND position('ipe.study_session' in query) > 0
   AND position('cycle_id' in query) > 0
   AND position('FOR UPDATE' in query) > 0
"""


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


def wait_until(predicate, timeout: float = 5.0, interval: float = 0.02) -> None:
    """조건이 참이 될 때까지 짧게 폴링한다. 시간 안에 참이 되지 않으면 실패한다."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(f"{timeout}초 안에 조건이 참이 되지 않았다")


def holds_session_lock(conn: psycopg.Connection, session_id: int) -> bool:
    """다른 트랜잭션이 그 세션 행을 잠그고 있는지 FOR UPDATE NOWAIT 로 판정한다."""
    try:
        conn.execute(
            "SELECT 1 FROM ipe.study_session WHERE id = %s FOR UPDATE NOWAIT", (session_id,)
        )
        return False
    except psycopg.errors.LockNotAvailable:
        return True


def replace_waits_on_open_round(conn: psycopg.Connection) -> bool:
    """새로 구성(POST)이 열린 라운드 잠금을 기다리는 백엔드가 있는지 본다."""
    return conn.execute(REPLACE_STEP2_WAITING_SQL).fetchone()["n"] > 0


def post_cycle(client: TestClient, subject_code: int, **extra):
    """사이클 생성 요청(201·409 판정은 테스트가 한다)."""
    return client.post(
        "/api/subject-cycles",
        json={"subjectCode": subject_code, **extra},
        headers=auth_headers(),
    )


def create_cycle(client: TestClient, tracker: ProgressTracker, subject_code: int, **extra) -> dict:
    """201 을 기대하는 사이클 생성. 테스트 끝에 지우도록 사이클을 추적한다."""
    response = post_cycle(client, subject_code, **extra)
    assert response.status_code == 201, response.text
    body = response.json()
    tracker.track_cycle(body["id"])
    return body


def subject_overview(client: TestClient, subject_code: int) -> dict:
    """홈 요약에서 그 과목 1행."""
    response = client.get("/api/subject-cycles/overview")
    assert response.status_code == 200, response.text
    items = response.json()
    assert len(items) == 5, items
    return next(item for item in items if item["subjectCode"] == subject_code)


def content_groups(conn: psycopg.Connection, subject_code: int) -> dict[str, list[str]]:
    """과목 문항을 API 의 중복 판정(content_key)으로 묶는다 — 테스트의 검산용."""
    where, params = queries.question_filters(subject_code=subject_code)
    groups: dict[str, list[str]] = {}
    for row in queries.fetch_content_rows(conn, where=where, params=params):
        groups.setdefault(queries.content_key(row), []).append(row["id"])
    return groups


def wrong_choice(answer: int) -> int:
    return 1 if answer != 1 else 2


def snapshot_slots(tracker: ProgressTracker, slots: list[dict]) -> None:
    """채점할 슬롯 문항의 study_state 를 미리 기억한다(테스트 끝에 복원)."""
    for row in slots:
        tracker.snapshot_state(row["question_id"])


def open_rounds(db_conn, cycle_id: int) -> list[dict]:
    return db_conn.execute(
        "SELECT id, round_no, finished_at FROM ipe.study_session"
        " WHERE cycle_id = %s AND finished_at IS NULL ORDER BY round_no",
        (cycle_id,),
    ).fetchall()


def test_overview_unique_counts_match_content_key(live_client, db_conn):
    """홈 요약의 과목별 고유 문항 수는 content_key 그룹 수(176·194·194·199·181)다."""
    response = live_client.get("/api/subject-cycles/overview")
    assert response.status_code == 200, response.text
    items = response.json()

    assert [item["subjectCode"] for item in items] == [1, 2, 3, 4, 5]
    assert {item["subjectCode"]: item["uniqueQuestionCount"] for item in items} == (
        UNIQUE_QUESTION_COUNTS
    )
    # 테스트가 직접 센 그룹 수와도 같다(과목으로 먼저 거른 뒤 묶어 교차 과목 그룹은 양쪽에 한 번씩 든다).
    assert {code: len(content_groups(db_conn, code)) for code in UNIQUE_QUESTION_COUNTS} == (
        UNIQUE_QUESTION_COUNTS
    )


def test_cross_subject_duplicate_group_enters_each_subject_once(live_client, tracker, db_conn):
    """과목이 다른 같은 내용 그룹(2023-1-001=2023-1-023)은 과목으로 먼저 거른 뒤 묶는다.

    1과목 사이클에는 2023-1-001 이, 2과목 사이클에는 2023-1-023 이 들어가고, 각 사이클 안에서
    같은 내용이 두 번 나오지 않는다(설계 2.3·4.5절).
    """
    pair = {"2023-1-001": 1, "2023-1-023": 2}
    keys = {}
    for question_id in pair:
        where, params = queries.question_filters(question_id=question_id)
        rows = queries.fetch_content_rows(db_conn, where=where, params=params)
        assert len(rows) == 1, rows
        keys[question_id] = queries.content_key(rows[0])
    assert len(set(keys.values())) == 1, keys

    for subject_code in pair.values():
        created = create_cycle(live_client, tracker, subject_code)
        slots = slot_questions(db_conn, created["rounds"][0]["sessionId"])
        slot_ids = [row["question_id"] for row in slots]
        groups = content_groups(db_conn, subject_code)
        owner = {question_id: key for key, ids in groups.items() for question_id in ids}
        assert len({owner[question_id] for question_id in slot_ids}) == len(slot_ids)
        assert len(slot_ids) == UNIQUE_QUESTION_COUNTS[subject_code]
        assert [question_id for question_id in pair if pair[question_id] == subject_code][0] in (
            slot_ids
        )
        assert len(set(slot_ids) & set(pair)) == 1


def test_cycle_from_api_runs_review_rounds_then_completes(live_client, tracker, db_conn):
    """생성 → 라운드 1 전체 풀이 → 오답 라운드 반복 → 완료까지 API 만으로 확인한다."""
    subject_code = 1
    expected_items = UNIQUE_QUESTION_COUNTS[subject_code]
    groups = content_groups(db_conn, subject_code)
    assert subject_overview(live_client, subject_code)["status"] == "not_started"

    created = create_cycle(live_client, tracker, subject_code)
    cycle_id = created["id"]
    assert created["subjectCode"] == subject_code and created["status"] == "active"
    assert created["endedAt"] is None
    assert len(created["rounds"]) == 1
    round1 = created["rounds"][0]
    assert round1["roundNo"] == 1 and round1["mode"] == "subject"
    assert round1["itemCount"] == expected_items and round1["answered"] == 0
    round1_id = round1["sessionId"]

    # 슬롯 = 그룹마다 1개(내용 중복 없음)이고 대표는 가장 최근 회차(id 최대)다.
    slots = slot_questions(db_conn, round1_id)
    assert len(slots) == expected_items
    owner = {question_id: key for key, ids in groups.items() for question_id in ids}
    assert {owner[row["question_id"]] for row in slots} == set(groups)
    for row in slots:
        assert row["question_id"] == max(groups[owner[row["question_id"]]])
    # 순서는 무작위로 섞인다(seq 가 id 순서가 아니다).
    slot_ids = [row["question_id"] for row in slots]
    assert slot_ids != sorted(slot_ids)

    overview = subject_overview(live_client, subject_code)
    assert overview["status"] == "first_pass"
    assert overview["uniqueQuestionCount"] == expected_items
    assert overview["cycle"]["id"] == cycle_id
    assert overview["cycle"]["firstRound"] == {
        "sessionId": round1_id,
        "roundNo": 1,
        "itemCount": expected_items,
        "answered": 0,
        "correct": 0,
    }

    # 라운드 1: 앞의 3문항을 틀리고 나머지를 맞힌다 → 라운드 2(오답 3개)가 생긴다.
    snapshot_slots(tracker, slots)
    wrong_seqs = {row["seq"] for row in slots[:3]}
    for row in slots[:-1]:
        choice = wrong_choice(row["answer"]) if row["seq"] in wrong_seqs else row["answer"]
        answer = put_slot(live_client, round1_id, row["seq"], choice)
        assert answer.status_code == 200, answer.text
        assert answer.json()["session"]["finished"] is False
    last = slots[-1]
    last_choice = wrong_choice(last["answer"]) if last["seq"] in wrong_seqs else last["answer"]
    closed = put_slot(live_client, round1_id, last["seq"], last_choice)
    assert closed.status_code == 200, closed.text

    closed_body = closed.json()
    assert closed_body["session"]["finished"] is True and closed_body["session"]["nextSeq"] is None
    assert closed_body["roundResult"] == {
        "roundNo": 1,
        "itemCount": expected_items,
        "correct": expected_items - 3,
        "wrong": 3,
    }
    assert closed_body["cycle"]["status"] == "active"
    assert closed_body["cycle"]["nextRoundNo"] == 2
    assert closed_body["cycle"]["nextItemCount"] == 3
    round2_id = closed_body["cycle"]["nextSessionId"]
    assert round2_id is not None and round2_id != round1_id

    overview = subject_overview(live_client, subject_code)
    assert overview["status"] == "reviewing"
    assert overview["cycle"]["firstRound"] == {
        "sessionId": round1_id,
        "roundNo": 1,
        "itemCount": expected_items,
        "answered": expected_items,
        "correct": expected_items - 3,
    }
    assert overview["cycle"]["currentRound"] == {
        "sessionId": round2_id,
        "roundNo": 2,
        "itemCount": 3,
        "answered": 0,
        "correct": 0,
    }

    # 라운드 2는 라운드 1의 오답만 담는다(같은 내용의 다른 회차 문항이 아니라 그 문항들이다).
    round2_slots = slot_questions(db_conn, round2_id)
    assert len(round2_slots) == 3
    assert {row["question_id"] for row in round2_slots} == {
        row["question_id"] for row in slots if row["seq"] in wrong_seqs
    }
    for row in round2_slots[:-1]:
        assert put_slot(live_client, round2_id, row["seq"], row["answer"]).status_code == 200
    last2 = round2_slots[-1]
    closed2 = put_slot(live_client, round2_id, last2["seq"], wrong_choice(last2["answer"]))
    assert closed2.status_code == 200, closed2.text

    closed2_body = closed2.json()
    assert closed2_body["roundResult"] == {"roundNo": 2, "itemCount": 3, "correct": 2, "wrong": 1}
    assert closed2_body["cycle"]["status"] == "active"
    assert closed2_body["cycle"]["nextRoundNo"] == 3
    assert closed2_body["cycle"]["nextItemCount"] == 1
    round3_id = closed2_body["cycle"]["nextSessionId"]

    # 라운드 3: 남은 한 문항을 맞히면 사이클이 완료된다.
    round3_slots = slot_questions(db_conn, round3_id)
    assert len(round3_slots) == 1
    final = put_slot(live_client, round3_id, round3_slots[0]["seq"], round3_slots[0]["answer"])
    assert final.status_code == 200, final.text
    final_body = final.json()
    assert final_body["roundResult"] == {"roundNo": 3, "itemCount": 1, "correct": 1, "wrong": 0}
    assert final_body["cycle"]["status"] == "completed"
    assert final_body["cycle"]["nextSessionId"] is None

    # 완료: 열린 라운드가 없고 홈 요약은 completed + currentRound null 이다.
    assert open_rounds(db_conn, cycle_id) == []
    overview = subject_overview(live_client, subject_code)
    assert overview["status"] == "completed"
    assert overview["cycle"]["id"] == cycle_id and overview["cycle"]["status"] == "completed"
    assert overview["cycle"]["endedAt"] is not None
    assert overview["cycle"]["currentRound"] is None

    detail = live_client.get(f"/api/subject-cycles/{cycle_id}")
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    assert detail_body["status"] == "completed" and detail_body["endedAt"] is not None
    assert [round_["roundNo"] for round_ in detail_body["rounds"]] == [1, 2, 3]
    assert [round_["mode"] for round_ in detail_body["rounds"]] == ["subject", "review", "review"]
    assert [round_["itemCount"] for round_ in detail_body["rounds"]] == [expected_items, 3, 1]
    assert [round_["correct"] for round_ in detail_body["rounds"]] == [expected_items - 3, 2, 1]
    assert [round_["answered"] for round_ in detail_body["rounds"]] == [expected_items, 3, 1]
    assert all(round_["finishedAt"] is not None for round_ in detail_body["rounds"])
    assert all(round_["endReason"] == "finished" for round_ in detail_body["rounds"])


def test_cycle_all_correct_first_round_completes_immediately(live_client, tracker, db_conn):
    """라운드 1을 전부 맞히면 다음 라운드 없이 곧바로 완료된다(설계 4.5절 5번)."""
    subject_code = 2
    expected_items = UNIQUE_QUESTION_COUNTS[subject_code]
    assert subject_overview(live_client, subject_code)["status"] == "not_started"

    created = create_cycle(live_client, tracker, subject_code)
    cycle_id = created["id"]
    round1_id = created["rounds"][0]["sessionId"]
    slots = slot_questions(db_conn, round1_id)
    assert len(slots) == expected_items
    snapshot_slots(tracker, slots)

    for row in slots[:-1]:
        assert put_slot(live_client, round1_id, row["seq"], row["answer"]).status_code == 200
    last = slots[-1]
    final = put_slot(live_client, round1_id, last["seq"], last["answer"])
    assert final.status_code == 200, final.text
    body = final.json()

    assert body["roundResult"] == {
        "roundNo": 1,
        "itemCount": expected_items,
        "correct": expected_items,
        "wrong": 0,
    }
    assert body["cycle"]["status"] == "completed"
    assert body["cycle"]["nextSessionId"] is None and body["cycle"]["nextRoundNo"] is None

    # 다음 라운드를 만들지 않고 끝난다 — 사이클에 열린 라운드가 없다.
    assert open_rounds(db_conn, cycle_id) == []
    overview = subject_overview(live_client, subject_code)
    assert overview["status"] == "completed"
    assert overview["cycle"]["id"] == cycle_id
    assert overview["cycle"]["firstRound"]["correct"] == expected_items
    assert overview["cycle"]["currentRound"] is None

    detail = live_client.get(f"/api/subject-cycles/{cycle_id}").json()
    assert [round_["roundNo"] for round_ in detail["rounds"]] == [1]
    assert detail["rounds"][0]["endReason"] == "finished"


def test_cycle_conflict_then_replace_active_starts_new_cycle(live_client, tracker, db_conn):
    """진행 중 사이클이 있으면 409, replaceActive=true 면 중단하고 같은 과목을 새로 시작한다."""
    subject_code = 3
    expected_items = UNIQUE_QUESTION_COUNTS[subject_code]

    first = create_cycle(live_client, tracker, subject_code)
    old_cycle_id = first["id"]
    old_round_id = first["rounds"][0]["sessionId"]
    assert first["rounds"][0]["itemCount"] == expected_items

    conflict = post_cycle(live_client, subject_code)
    assert conflict.status_code == 409, conflict.text
    assert "replaceActive=true" in conflict.json()["detail"]
    # 409 는 아무것도 바꾸지 않는다 — 기존 라운드는 그대로 열려 있다.
    assert open_rounds(db_conn, old_cycle_id) != []

    second = create_cycle(live_client, tracker, subject_code, replaceActive=True)
    new_cycle_id = second["id"]
    assert new_cycle_id != old_cycle_id
    assert second["status"] == "active" and second["rounds"][0]["itemCount"] == expected_items
    assert second["rounds"][0]["sessionId"] != old_round_id

    # 기존 사이클과 그 열린 라운드는 abandoned 로 보존되고, 새 사이클만 진행 중이다.
    old_cycle = db_conn.execute(
        "SELECT status, ended_at FROM ipe.study_cycle WHERE id = %s", (old_cycle_id,)
    ).fetchone()
    assert old_cycle["status"] == "abandoned" and old_cycle["ended_at"] is not None
    old_round = db_conn.execute(
        "SELECT finished_at, end_reason FROM ipe.study_session WHERE id = %s", (old_round_id,)
    ).fetchone()
    assert old_round["finished_at"] is not None and old_round["end_reason"] == "abandoned"
    assert open_rounds(db_conn, old_cycle_id) == []
    assert db_conn.execute(
        "SELECT count(*)::int AS n FROM ipe.study_cycle WHERE subject_code = %s AND status = 'active'",
        (subject_code,),
    ).fetchone()["n"] == 1

    # 중단된 라운드에는 더 채점할 수 없다(중단 세션 409).
    rejected = put_slot(live_client, old_round_id, 1, 1)
    assert rejected.status_code == 409, rejected.text
    assert "중단된 세션" in rejected.json()["detail"]

    overview = subject_overview(live_client, subject_code)
    assert overview["status"] == "first_pass"
    assert overview["cycle"]["id"] == new_cycle_id

    # 목록 조회: 두 사이클이 모두 보이고 status 로 가를 수 있다.
    listed = live_client.get(
        "/api/subject-cycles", params={"subjectCode": subject_code, "limit": 10}
    ).json()
    assert {new_cycle_id, old_cycle_id} <= {item["id"] for item in listed}
    assert all(item["subjectCode"] == subject_code for item in listed)
    abandoned = live_client.get(
        "/api/subject-cycles", params={"subjectCode": subject_code, "status": "abandoned"}
    ).json()
    assert old_cycle_id in {item["id"] for item in abandoned}
    assert all(item["status"] == "abandoned" for item in abandoned)

    detail = live_client.get(f"/api/subject-cycles/{old_cycle_id}").json()
    assert detail["status"] == "abandoned" and detail["endedAt"] is not None
    assert detail["rounds"][0]["endReason"] == "abandoned"
    assert detail["rounds"][0]["answered"] == 0


def test_two_devices_starting_at_once_only_one_wins(live_client, tracker, db_conn):
    """두 기기에서 동시에 시작하면 study_cycle_active_uk 가 막아 하나만 201 이 된다(설계 4.6절)."""
    subject_code = 4
    results: dict[str, object] = {}

    def start(name: str) -> None:
        results[name] = post_cycle(live_client, subject_code)

    threads = [
        threading.Thread(target=start, args=(name,), name=f"start-{name}") for name in ("a", "b")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive(), "동시 시작 요청이 끝나지 않았다"

    responses = list(results.values())
    assert len(responses) == 2, results
    assert sorted(response.status_code for response in responses) == [201, 409], [
        (response.status_code, response.text) for response in responses
    ]
    winner = next(response for response in responses if response.status_code == 201)
    loser = next(response for response in responses if response.status_code == 409)
    cycle_id = winner.json()["id"]
    tracker.track_cycle(cycle_id)
    assert "replaceActive=true" in loser.json()["detail"]
    assert winner.json()["rounds"][0]["itemCount"] == UNIQUE_QUESTION_COUNTS[subject_code]

    # 진행 중 사이클은 하나뿐이다(진 쪽은 롤백돼 아무 행도 남기지 않는다).
    actives = db_conn.execute(
        "SELECT id FROM ipe.study_cycle WHERE subject_code = %s AND status = 'active'",
        (subject_code,),
    ).fetchall()
    assert [row["id"] for row in actives] == [cycle_id]
    assert subject_overview(live_client, subject_code)["cycle"]["id"] == cycle_id


def test_last_slot_grade_races_replace_active(live_client, tracker, db_conn):
    """마지막 문항 제출 vs 새로 구성(설계 4.6절).

    채점이 세션을 잠근 채 라운드를 닫는 동안 새로 구성이 들어오면, 새로 구성은 열린 라운드
    잠금을 기다렸다가 그 라운드가 이미 닫힌 것을 보고(문장 스냅샷) 사이클만 중단한다. 그래서
    **중단된 사이클에 열린 라운드가 하나 남을 수 있다** — 남은 라운드의 마지막 슬롯을 채점하면
    `advance_round_if_complete` 가 라운드만 닫고 새 라운드를 만들지 않아 스스로 회복한다.
    """
    subject_code = 5
    picked = db_conn.execute(
        "SELECT id, answer FROM ipe.question WHERE subject_code = %s ORDER BY id LIMIT 2",
        (subject_code,),
    ).fetchall()
    for row in picked:
        tracker.snapshot_state(row["id"])

    # 2문항짜리 라운드 1을 직접 만든다(목록 구성 자체는 위 테스트들이 API 로 확인한다).
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
    # 첫 문항을 틀려 둔다 → 마지막 슬롯이 끝나면 라운드 2(오답 1개)가 만들어진다.
    first = put_slot(live_client, round1_id, 1, wrong_choice(picked[0]["answer"]))
    assert first.status_code == 200, first.text

    results: dict[str, object] = {}

    def grade_last() -> None:
        results["grade"] = put_slot(live_client, round1_id, 2, picked[1]["answer"])

    def replace_active() -> None:
        response = post_cycle(live_client, subject_code, replaceActive=True)
        results["replace"] = response
        # 뒤에서 단언이 실패해도 새 사이클이 남지 않도록 응답을 받자마자 추적한다.
        if response.status_code == 201:
            tracker.track_cycle(response.json()["id"])

    blocker = lock_connection(autocommit=False)  # 사이클 행 잠금으로 채점을 라운드 종료 직전에 세운다
    probe = lock_connection(autocommit=True)
    grade_thread = threading.Thread(target=grade_last, name="grade-last")
    replace_thread: threading.Thread | None = None
    try:
        blocker.execute("SELECT 1 FROM ipe.study_cycle WHERE id = %s FOR UPDATE", (cycle_id,))
        grade_thread.start()
        # 채점이 세션 행 잠금을 잡았는지 확인한다 — 이 잠금이 새로 구성의 2단계를 막는다.
        wait_until(lambda: holds_session_lock(probe, round1_id))

        replace_thread = threading.Thread(target=replace_active, name="replace-active")
        replace_thread.start()
        # 새로 구성이 열린 라운드 잠금을 기다리는지 확인한다 — 그래야 2단계 스냅샷이 라운드 종료 전이다.
        wait_until(lambda: replace_waits_on_open_round(probe))
    finally:
        blocker.rollback()  # 사이클 잠금 해제 — 채점이 라운드를 닫고 다음 라운드를 만든다
        blocker.close()
        probe.close()
        grade_thread.join(timeout=20)
        if replace_thread is not None:
            replace_thread.join(timeout=20)

    assert not grade_thread.is_alive() and "grade" in results, "채점 요청이 끝나지 않았다"
    grade_response = results["grade"]
    assert grade_response.status_code == 200, grade_response.text
    assert grade_response.json()["roundResult"] == {
        "roundNo": 1,
        "itemCount": 2,
        "correct": 1,
        "wrong": 1,
    }

    replace_response = results.get("replace")
    assert replace_response is not None and replace_thread is not None
    assert not replace_thread.is_alive(), "새로 구성 요청이 끝나지 않았다"
    assert replace_response.status_code == 201, replace_response.text
    new_cycle_id = replace_response.json()["id"]
    assert new_cycle_id != cycle_id

    # 남는 상태: 기존 사이클은 abandoned, 그 사이클에는 열린 라운드(2라운드)가 하나 남는다.
    assert db_conn.execute(
        "SELECT status FROM ipe.study_cycle WHERE id = %s", (cycle_id,)
    ).fetchone()["status"] == "abandoned"
    leftover = open_rounds(db_conn, cycle_id)
    assert len(leftover) == 1, leftover
    assert leftover[0]["round_no"] == 2
    leftover_id = leftover[0]["id"]

    # 회복: 남은 라운드의 마지막 슬롯을 채점하면 라운드만 닫히고 사이클은 abandoned 로 남는다.
    leftover_slots = slot_questions(db_conn, leftover_id)
    assert len(leftover_slots) == 1
    recovered = put_slot(live_client, leftover_id, leftover_slots[0]["seq"], leftover_slots[0]["answer"])
    assert recovered.status_code == 200, recovered.text
    recovered_body = recovered.json()
    assert recovered_body["roundResult"] == {"roundNo": 2, "itemCount": 1, "correct": 1, "wrong": 0}
    assert recovered_body["cycle"]["status"] == "abandoned"
    assert recovered_body["cycle"]["nextSessionId"] is None
    assert recovered_body["cycle"]["nextRoundNo"] is None

    assert open_rounds(db_conn, cycle_id) == []
    # 라운드 1(채점으로 종료)과 남은 라운드(회복 채점으로 종료) 둘 다 정상 종료로 남는다.
    assert db_conn.execute(
        "SELECT count(*)::int AS n FROM ipe.study_session"
        " WHERE cycle_id = %s AND finished_at IS NOT NULL AND end_reason = 'finished'",
        (cycle_id,),
    ).fetchone()["n"] == 2
    # 새 사이클은 라운드 1 진행 중이고, 홈 요약도 새 사이클을 본다.
    overview = subject_overview(live_client, subject_code)
    assert overview["status"] == "first_pass"
    assert overview["cycle"]["id"] == new_cycle_id
    assert open_rounds(db_conn, new_cycle_id) != []
