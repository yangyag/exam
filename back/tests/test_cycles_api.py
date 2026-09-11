"""과목 사이클 라우터 단위 테스트(가짜 DB).

- 생성: 그룹 대표(가장 최근 회차)·셔플·409·새로 구성·유니크 인덱스 위반 409·SQL 순서.
- 조회: 목록 필터·단건·404·홈 요약 상태 4종.
실제 라운드 전환과 잠금 경합은 `test_integration_cycles.py` 가 고정한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

import psycopg

from helpers import assert_no_answer_leak

TS = datetime(2026, 9, 11, 5, 25, 50, tzinfo=timezone.utc)
TS_TEXT = "2026-09-11T05:25:50"

SUBJECT_FRAGMENT = "SELECT code, name FROM ipe.subject WHERE code"
SUBJECTS_FRAGMENT = "SELECT code, name FROM ipe.subject ORDER BY code"
CONTENT_FRAGMENT = "coalesce(ch.choice_texts, ARRAY[]::text[])"
CYCLE_SELECT_FRAGMENT = "FROM ipe.study_cycle c JOIN ipe.subject sj"
ACTIVE_CYCLE_FRAGMENT = "FROM ipe.study_cycle WHERE subject_code = %s AND status = 'active'"
ROUNDS_FRAGMENT = "FROM ipe.study_session s LEFT JOIN ipe.study_session_item i"
PICK_FRAGMENT = "FROM ipe.study_cycle c WHERE c.status IN ('active', 'completed')"
OPEN_ROUND_FRAGMENT = "FROM ipe.study_session WHERE cycle_id = ANY(%s) AND finished_at IS NULL"
SESSION_INSERT_FRAGMENT = "INSERT INTO ipe.study_session (mode"
SLOT_INSERT_FRAGMENT = "INSERT INTO ipe.study_session_item"
CYCLE_INSERT_FRAGMENT = "INSERT INTO ipe.study_cycle"
ROUND_LOCK_FRAGMENT = "FROM ipe.study_session WHERE cycle_id = %s AND finished_at IS NULL FOR UPDATE"
CYCLE_LOCK_FRAGMENT = "FROM ipe.study_cycle WHERE id = %s FOR UPDATE"
SESSION_ABANDON_FRAGMENT = "SET finished_at = now(), end_reason = 'abandoned'"
CYCLE_ABANDON_FRAGMENT = "SET status = 'abandoned', ended_at = now()"


def content_row(question_id: str, stem: str) -> dict:
    """`queries.fetch_content_rows` 가 돌려주는 행과 같은 모양."""
    return {
        "id": question_id,
        "stem": stem,
        "passage": None,
        "passage_kind": None,
        "figure_needed": False,
        "figure_kind": None,
        "figure_alt": None,
        "choice_texts": ["보기1", "보기2", "보기3", "보기4"],
    }


def content_rows_by_subject(rows_by_subject: dict[int, list[dict]]):
    """과목 코드(WHERE 파라미터)마다 다른 행을 돌려주는 규칙."""

    def source(sql: str, params) -> list[dict]:
        return rows_by_subject.get(params[0], [])

    return source


def cycle_row(
    cycle_id: int,
    subject_code: int = 1,
    status: str = "active",
    ended_at: datetime | None = None,
    subject_name: str = "소프트웨어 설계",
) -> dict:
    return {
        "id": cycle_id,
        "subject_code": subject_code,
        "subject_name": subject_name,
        "status": status,
        "created_at": TS,
        "ended_at": ended_at,
    }


def round_row(
    cycle_id: int,
    session_id: int,
    round_no: int,
    mode: str,
    item_count: int,
    answered: int,
    correct: int,
    finished_at: datetime | None = None,
    end_reason: str | None = None,
) -> dict:
    return {
        "cycle_id": cycle_id,
        "session_id": session_id,
        "round_no": round_no,
        "mode": mode,
        "item_count": item_count,
        "answered": answered,
        "correct": correct,
        "started_at": TS,
        "finished_at": finished_at,
        "end_reason": end_reason,
    }


def pick_row(cycle_id: int, subject_code: int, status: str, ended_at: datetime | None = None) -> dict:
    """홈 요약의 사이클 1행(HOME_CYCLE_PICK_SQL 결과)."""
    return {
        "id": cycle_id,
        "subject_code": subject_code,
        "status": status,
        "created_at": TS,
        "ended_at": ended_at,
    }


def create_rules(**overrides) -> dict:
    """생성 성공 경로의 기본 규칙. 테스트마다 필요한 것만 덮어쓴다."""
    rules = {
        SUBJECT_FRAGMENT: [{"code": 1, "name": "소프트웨어 설계"}],
        CONTENT_FRAGMENT: [content_row("2026-1-001", "A")],
        SLOT_INSERT_FRAGMENT: [],
        SESSION_INSERT_FRAGMENT: [{"id": 11}],
        CYCLE_INSERT_FRAGMENT: [{"id": 7}],
        CYCLE_SELECT_FRAGMENT: [cycle_row(7)],
        ROUNDS_FRAGMENT: [round_row(7, 11, 1, "subject", 1, 0, 0)],
    }
    rules.update(overrides)
    return rules


def test_create_cycle_dedupes_groups_and_builds_round_one(fake_db, client):
    """과목 문항을 content_key 로 묶고 그룹 대표(가장 최근 회차)를 셔플해 라운드 1 슬롯으로 만든다."""
    fake = fake_db(
        create_rules(
            **{
                CONTENT_FRAGMENT: [
                    content_row("2026-1-001", "A"),
                    content_row("2025-3-002", "A"),  # 같은 내용의 옛 회차 — 대표가 아니다
                    content_row("2026-1-003", "B"),
                    content_row("2024-2-004", "B"),
                    content_row("2026-1-005", "C"),
                ],
                ROUNDS_FRAGMENT: [round_row(7, 11, 1, "subject", 3, 0, 0)],
            }
        )
    )
    response = client.post("/api/subject-cycles", json={"subjectCode": 1})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] == 7
    assert body["subjectCode"] == 1 and body["subjectName"] == "소프트웨어 설계"
    assert body["status"] == "active" and body["endedAt"] is None
    assert body["startedAt"].startswith(TS_TEXT)
    assert len(body["rounds"]) == 1
    round1 = body["rounds"][0]
    assert round1["sessionId"] == 11 and round1["roundNo"] == 1 and round1["mode"] == "subject"
    assert round1["itemCount"] == 3 and round1["answered"] == 0 and round1["correct"] == 0
    assert round1["finishedAt"] is None and round1["endReason"] is None
    assert_no_answer_leak(body)

    # 슬롯은 그룹 대표 3개(무작위 순서) — 옛 회차 문항은 빠진다.
    assert fake.single(SESSION_INSERT_FRAGMENT)[1] == ("subject", None, 1, 7, 1)
    slot_sql, slot_params = fake.single(SLOT_INSERT_FRAGMENT)
    assert slot_params[0] == 11
    assert sorted(slot_params[1]) == ["2026-1-001", "2026-1-003", "2026-1-005"]
    assert "ORDINALITY" in slot_sql


def test_create_cycle_unknown_subject_is_404(fake_db, client):
    """없는 과목이면 문항 조회 전에 404 로 끝난다."""
    fake = fake_db(create_rules(**{SUBJECT_FRAGMENT: []}))
    response = client.post("/api/subject-cycles", json={"subjectCode": 5})

    assert response.status_code == 404
    assert fake.executed(CONTENT_FRAGMENT) == []
    assert fake.executed(CYCLE_INSERT_FRAGMENT) == []


def test_create_cycle_conflicts_when_active_cycle_exists(fake_db, client):
    """진행 중 사이클이 있으면 replaceActive 없이는 409 이고 아무것도 만들지 않는다."""
    fake = fake_db(
        create_rules(
            **{
                ACTIVE_CYCLE_FRAGMENT: [
                    {"id": 5, "subject_code": 1, "status": "active", "ended_at": None}
                ]
            }
        )
    )
    response = client.post("/api/subject-cycles", json={"subjectCode": 1})

    assert response.status_code == 409
    assert "replaceActive=true" in response.json()["detail"]
    assert fake.executed(CYCLE_INSERT_FRAGMENT) == []
    assert fake.executed(SESSION_INSERT_FRAGMENT) == []


def test_create_cycle_replace_active_closes_cycle_then_creates_new_one(fake_db, client):
    """replaceActive=true 는 열린 라운드 → 사이클 순서로 잠그고 중단한 뒤 새 사이클을 만든다."""
    fake = fake_db(
        create_rules(
            **{
                ACTIVE_CYCLE_FRAGMENT: [
                    {"id": 5, "subject_code": 1, "status": "active", "ended_at": None}
                ],
                ROUND_LOCK_FRAGMENT: [{"id": 42}],
                CYCLE_LOCK_FRAGMENT: [{"id": 5, "subject_code": 1, "status": "active"}],
                SESSION_ABANDON_FRAGMENT: [],
                CYCLE_ABANDON_FRAGMENT: [
                    {"id": 5, "subject_code": 1, "status": "abandoned", "ended_at": TS}
                ],
                CYCLE_INSERT_FRAGMENT: [{"id": 6}],
                SESSION_INSERT_FRAGMENT: [{"id": 12}],
                CYCLE_SELECT_FRAGMENT: [cycle_row(6)],
                ROUNDS_FRAGMENT: [round_row(6, 12, 1, "subject", 1, 0, 0)],
            }
        )
    )
    response = client.post("/api/subject-cycles", json={"subjectCode": 1, "replaceActive": True})

    assert response.status_code == 201, response.text
    assert response.json()["id"] == 6
    assert fake.single(SESSION_ABANDON_FRAGMENT)[1] == ([42],)
    assert fake.single(CYCLE_ABANDON_FRAGMENT)[1] == (5,)

    # 잠금 순서는 세션 → 사이클(설계 4.6절)이고, 중단과 새 사이클 생성이 한 트랜잭션 안에 있다.
    sqls = [sql for sql, _ in fake.calls]
    positions = [
        next(i for i, sql in enumerate(sqls) if ROUND_LOCK_FRAGMENT in sql),
        next(i for i, sql in enumerate(sqls) if CYCLE_LOCK_FRAGMENT in sql),
        next(i for i, sql in enumerate(sqls) if sql.startswith("UPDATE ipe.study_cycle SET status")),
        next(i for i, sql in enumerate(sqls) if sql.startswith(CYCLE_INSERT_FRAGMENT)),
        next(i for i, sql in enumerate(sqls) if sql.startswith(SESSION_INSERT_FRAGMENT)),
    ]
    assert positions == sorted(positions), positions


def test_create_cycle_active_index_violation_becomes_409(fake_db, client):
    """두 기기 동시 시작 경합: study_cycle_active_uk 위반은 409 다(설계 4.6절)."""

    def violating(sql: str, params):
        raise psycopg.errors.UniqueViolation(
            'duplicate key value violates unique constraint "study_cycle_active_uk"'
        )

    fake_db(create_rules(**{CYCLE_INSERT_FRAGMENT: violating}))
    response = client.post("/api/subject-cycles", json={"subjectCode": 1})

    assert response.status_code == 409
    assert "진행 중인 사이클" in response.json()["detail"]


def test_list_cycles_filters_and_paginates(fake_db, client):
    """목록은 subjectCode·status·limit·offset 을 SQL 로 넘기고 라운드 집계를 붙인다."""
    fake = fake_db(
        {
            CYCLE_SELECT_FRAGMENT: [
                cycle_row(9, 3, "completed", TS, subject_name="데이터베이스 구축"),
                cycle_row(4, 3, "abandoned", TS, subject_name="데이터베이스 구축"),
            ],
            ROUNDS_FRAGMENT: [
                round_row(9, 30, 1, "subject", 194, 194, 150, finished_at=TS, end_reason="finished")
            ],
        }
    )
    response = client.get(
        "/api/subject-cycles",
        params={"subjectCode": 3, "status": "completed", "limit": 5, "offset": 10},
    )

    assert response.status_code == 200, response.text
    items = response.json()
    assert [item["id"] for item in items] == [9, 4]
    assert items[0]["rounds"][0]["correct"] == 150
    assert items[0]["rounds"][0]["finishedAt"].startswith(TS_TEXT)
    assert items[1]["rounds"] == []
    sql, params = fake.single("JOIN ipe.subject sj ON sj.code = c.subject_code WHERE")
    assert "c.subject_code = %s" in sql and "c.status = %s" in sql
    assert params == [3, "completed", 5, 10]


def test_list_cycles_rejects_unknown_status(fake_db, client):
    """status 는 세 값만 받는다(422)."""
    fake_db({})
    assert client.get("/api/subject-cycles", params={"status": "paused"}).status_code == 422


def test_get_cycle_detail_rounds_and_404(fake_db, client):
    fake_db({CYCLE_SELECT_FRAGMENT: []})
    missing = client.get("/api/subject-cycles/77")
    assert missing.status_code == 404
    assert "찾을 수 없습니다" in missing.json()["detail"]

    fake = fake_db(
        {
            CYCLE_SELECT_FRAGMENT: [cycle_row(9, 3, "completed", TS, subject_name="데이터베이스 구축")],
            ROUNDS_FRAGMENT: [
                round_row(9, 30, 1, "subject", 194, 194, 170, finished_at=TS, end_reason="finished"),
                round_row(9, 31, 2, "review", 24, 24, 24, finished_at=TS, end_reason="finished"),
            ],
        }
    )
    response = client.get("/api/subject-cycles/9")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == 9 and body["status"] == "completed"
    assert body["startedAt"].startswith(TS_TEXT) and body["endedAt"] is not None
    assert [round_["roundNo"] for round_ in body["rounds"]] == [1, 2]
    assert body["rounds"][1]["mode"] == "review" and body["rounds"][1]["itemCount"] == 24
    assert body["rounds"][1]["roundNo"] == 2 and body["rounds"][1]["endReason"] == "finished"
    assert fake.single("WHERE c.id = %s")[1] == (9,)
    assert_no_answer_leak(body)


def test_overview_not_started_with_unique_counts(fake_db, client):
    """사이클이 없는 과목은 not_started 이고, 고유 문항 수는 content_key 그룹 수다."""
    fake = fake_db(
        {
            SUBJECTS_FRAGMENT: [
                {"code": 1, "name": "소프트웨어 설계"},
                {"code": 2, "name": "소프트웨어 개발"},
            ],
            CONTENT_FRAGMENT: content_rows_by_subject(
                {
                    1: [
                        content_row("2026-1-001", "A"),
                        content_row("2025-3-002", "A"),
                        content_row("2026-1-003", "B"),
                    ],
                    2: [content_row("2026-1-021", "C"), content_row("2024-2-022", "C")],
                }
            ),
            PICK_FRAGMENT: [],
        }
    )
    response = client.get("/api/subject-cycles/overview")

    assert response.status_code == 200, response.text
    items = response.json()
    assert [item["subjectCode"] for item in items] == [1, 2]
    assert [item["status"] for item in items] == ["not_started", "not_started"]
    assert [item["uniqueQuestionCount"] for item in items] == [2, 1]
    assert all(item["cycle"] is None for item in items)
    assert_no_answer_leak(items)

    # 중단(abandoned) 사이클은 홈 상태의 근거가 아니다 — 진행 중·완료만 고른다.
    pick_sql, _ = fake.single(PICK_FRAGMENT)
    assert "status IN ('active', 'completed')" in pick_sql
    assert "(c.status = 'active') DESC" in pick_sql


def test_overview_active_cycle_is_first_pass_or_reviewing(fake_db, client):
    """진행 중 사이클의 열린 라운드가 1이면 first_pass, 2 이상이면 reviewing 이다."""
    fake_db(
        {
            SUBJECTS_FRAGMENT: [
                {"code": 1, "name": "소프트웨어 설계"},
                {"code": 2, "name": "소프트웨어 개발"},
            ],
            CONTENT_FRAGMENT: content_rows_by_subject(
                {1: [content_row("2026-1-001", "A")], 2: [content_row("2026-1-021", "C")]}
            ),
            PICK_FRAGMENT: [pick_row(3, 1, "active"), pick_row(4, 2, "active")],
            ROUNDS_FRAGMENT: [
                round_row(3, 12, 1, "subject", 176, 100, 80),
                round_row(4, 20, 1, "subject", 194, 194, 150, finished_at=TS, end_reason="finished"),
                round_row(4, 21, 2, "review", 44, 5, 3),
            ],
            OPEN_ROUND_FRAGMENT: [
                {"cycle_id": 3, "session_id": 12, "round_no": 1},
                {"cycle_id": 4, "session_id": 21, "round_no": 2},
            ],
        }
    )
    items = client.get("/api/subject-cycles/overview").json()
    first, second = items

    assert first["status"] == "first_pass"
    assert first["cycle"]["id"] == 3 and first["cycle"]["status"] == "active"
    assert first["cycle"]["endedAt"] is None and first["cycle"]["startedAt"].startswith(TS_TEXT)
    assert first["cycle"]["firstRound"] == {
        "sessionId": 12,
        "roundNo": 1,
        "itemCount": 176,
        "answered": 100,
        "correct": 80,
    }
    assert first["cycle"]["currentRound"] == first["cycle"]["firstRound"]

    assert second["status"] == "reviewing"
    assert second["cycle"]["firstRound"] == {
        "sessionId": 20,
        "roundNo": 1,
        "itemCount": 194,
        "answered": 194,
        "correct": 150,
    }
    assert second["cycle"]["currentRound"] == {
        "sessionId": 21,
        "roundNo": 2,
        "itemCount": 44,
        "answered": 5,
        "correct": 3,
    }


def test_overview_completed_cycle_has_no_current_round(fake_db, client):
    """완료한 사이클은 status=completed 이고 currentRound 가 null 이다(설계 5.1절)."""
    fake_db(
        {
            SUBJECTS_FRAGMENT: [{"code": 1, "name": "소프트웨어 설계"}],
            CONTENT_FRAGMENT: content_rows_by_subject({1: [content_row("2026-1-001", "A")]}),
            PICK_FRAGMENT: [pick_row(8, 1, "completed", TS)],
            ROUNDS_FRAGMENT: [
                round_row(8, 40, 1, "subject", 176, 176, 176, finished_at=TS, end_reason="finished")
            ],
            OPEN_ROUND_FRAGMENT: [],
        }
    )
    item = client.get("/api/subject-cycles/overview").json()[0]

    assert item["status"] == "completed"
    assert item["cycle"]["id"] == 8 and item["cycle"]["status"] == "completed"
    assert item["cycle"]["endedAt"].startswith(TS_TEXT)
    assert item["cycle"]["currentRound"] is None
    assert item["cycle"]["firstRound"] == {
        "sessionId": 40,
        "roundNo": 1,
        "itemCount": 176,
        "answered": 176,
        "correct": 176,
    }


def test_overview_active_cycle_without_open_round_uses_last_round(fake_db, client):
    """경합으로 열린 라운드가 남지 않은 비정상 상태에서도 상태는 마지막 라운드로 판정한다."""
    fake_db(
        {
            SUBJECTS_FRAGMENT: [{"code": 1, "name": "소프트웨어 설계"}],
            CONTENT_FRAGMENT: content_rows_by_subject({1: [content_row("2026-1-001", "A")]}),
            PICK_FRAGMENT: [pick_row(5, 1, "active")],
            ROUNDS_FRAGMENT: [
                round_row(5, 50, 1, "subject", 176, 176, 150, finished_at=TS, end_reason="finished"),
                round_row(5, 51, 2, "review", 26, 26, 20, finished_at=TS, end_reason="finished"),
            ],
            OPEN_ROUND_FRAGMENT: [],
        }
    )
    item = client.get("/api/subject-cycles/overview").json()[0]

    assert item["status"] == "reviewing"
    assert item["cycle"]["currentRound"] is None
    assert item["cycle"]["firstRound"]["correct"] == 150
