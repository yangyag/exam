"""문항 조회 API 의 정답 누출 방지 테스트(DB 없이 가짜 커넥션으로).

응답 JSON·OpenAPI 스키마·실행된 SELECT 세 곳 모두에서 정답·해설이 없어야 한다.
"""
from __future__ import annotations

import random

import pytest

from app.queries import content_key, pick_unique_random_ids

from helpers import assert_no_answer_leak, assert_select_hides_secrets
from sample_data import question_content_row, question_row

QUESTION_SELECT = "FROM ipe.question q"
COUNT_SELECT = "count(*)::int AS n FROM ipe.question q"
EXAM_EXISTS = "SELECT 1 FROM ipe.exam WHERE id"
CONTENT_KEY_SELECT = "choice_texts"
FULL_QUESTION_SELECT = "coalesce(ch.choices"


def test_get_question_hides_answer(client, fake_db):
    """단건 조회 응답에 정답·해설·보기별 해설이 없고, 보기는 번호와 본문만 싣는다."""
    fake = fake_db(
        {
            QUESTION_SELECT: [
                question_row(
                    figure_needed=True,
                    figure_kind="diagram",
                    figure_image="figures/2022-1/001.png",
                    figure_alt="순서도",
                )
            ]
        }
    )
    response = client.get("/api/questions/2022-1-001")
    assert response.status_code == 200
    body = response.json()

    assert body["id"] == "2022-1-001"
    assert body["figure"]["imageUrl"] == "/figures/2022-1/001.png"
    assert_no_answer_leak(body)
    assert [choice["no"] for choice in body["choices"]] == [1, 2, 3, 4]
    assert set(body["choices"][0]) == {"no", "text"}

    # 실행된 조회 SQL 자체가 정답·해설 컬럼을 건드리지 않아야 한다.
    assert_select_hides_secrets(fake.select_sqls())


def test_random_questions_returns_one_per_content_group(client, fake_db):
    """내용이 같은 문항은 한 응답에 하나만 나오고, 뽑힌 대표만 문항 전체 조회로 넘어간다."""
    contents = [
        question_content_row(),
        question_content_row(id="2023-2-050"),  # 2022-1-001 과 내용이 같다
        question_content_row(id="2022-1-002", stem="다른 내용의 질문?"),
    ]
    fulls = [
        question_row(),
        question_row(id="2023-2-050", number=50),
        question_row(id="2022-1-002", number=2),
    ]
    fake = fake_db({CONTENT_KEY_SELECT: contents, FULL_QUESTION_SELECT: fulls})
    response = client.get("/api/questions/random", params={"count": 10})
    assert response.status_code == 200
    items = response.json()
    ids = [item["id"] for item in items]
    assert len(ids) == 2, ids
    assert "2022-1-002" in ids
    assert len({"2022-1-001", "2023-2-050"} & set(ids)) == 1, "중복 그룹에서 두 문항이 나왔다"
    for item in items:
        assert_no_answer_leak(item)
    assert_select_hides_secrets(fake.select_sqls())
    assert fake.single(FULL_QUESTION_SELECT)[1] == [ids]


def test_random_questions_shortfall_returns_available(client, fake_db):
    """고유 후보가 count 보다 적으면 오류가 아니라 가용한 만큼만 돌려준다(부족분 허용)."""
    contents = [
        question_content_row(),
        question_content_row(id="2023-2-050"),
    ]
    fake_db(
        {
            CONTENT_KEY_SELECT: contents,
            FULL_QUESTION_SELECT: [question_row(), question_row(id="2023-2-050", number=50)],
        }
    )
    response = client.get("/api/questions/random", params={"count": 10})
    assert response.status_code == 200
    assert len(response.json()) == 1  # 두 행이 같은 내용이라 그룹이 하나뿐이다


def test_random_questions_count_limits_groups(client, fake_db):
    """count 가 고유 그룹 수보다 작으면 그만큼만 고른다."""
    contents = [
        question_content_row(id=f"2022-1-00{n}", stem=f"질문 {n}") for n in (1, 2, 3)
    ]
    fulls = [question_row(id=f"2022-1-00{n}", number=n) for n in (1, 2, 3)]
    fake_db({CONTENT_KEY_SELECT: contents, FULL_QUESTION_SELECT: fulls})
    response = client.get("/api/questions/random", params={"count": 2})
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_random_route_is_not_shadowed_by_single_question_route(client, fake_db):
    """/api/questions/random 이 /api/questions/{id} 로 해석되면 목록이 아니라 404/객체가 나온다."""
    fake_db({CONTENT_KEY_SELECT: [question_content_row()], FULL_QUESTION_SELECT: [question_row()]})
    response = client.get("/api/questions/random")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_content_key_ignores_only_commas():
    """중복 키는 쉼표만 무시하고 공백·기호는 그대로 본다(I-01)."""
    base = question_content_row(choice_texts=["가, 나", "다"])
    comma = question_content_row(choice_texts=["가 나", "다"])
    spaced = question_content_row(choice_texts=["가  나", "다"])
    symbol = question_content_row(choice_texts=["가; 나", "다"])

    assert content_key(base) == content_key(comma)
    assert content_key(base) != content_key(spaced)
    assert content_key(base) != content_key(symbol)


def test_pick_unique_random_ids_chooses_representative_randomly():
    """같은 내용 그룹의 대표는 매번 같은 문항으로 고정되지 않는다(대표 무작위)."""
    rows = [
        question_content_row(id="2022-1-001"),
        question_content_row(id="2023-2-050"),
    ]
    seen = set()
    for seed in range(10):
        random.seed(seed)
        seen.add(pick_unique_random_ids(rows, 1)[0])
    assert seen == {"2022-1-001", "2023-2-050"}


def test_exam_question_page_hides_answer_and_keeps_paging(client, fake_db):
    """회차 문항 목록도 누출 없이 total·limit·offset 을 정확히 돌려준다."""
    fake = fake_db(
        {
            COUNT_SELECT: [{"n": 105}],
            QUESTION_SELECT: [question_row(), question_row(id="2022-1-002", number=2)],
            EXAM_EXISTS: [{"?column?": 1}],
        }
    )
    response = client.get("/api/exams/2022-1/questions", params={"limit": 2, "offset": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 105
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert len(body["items"]) == 2
    for item in body["items"]:
        assert_no_answer_leak(item)

    _, params = fake.single("ORDER BY q.number")
    assert params == ["2022-1", 2, 1]
    assert_select_hides_secrets(fake.select_sqls())


def test_exam_question_filters_build_where_and_params(client, fake_db):
    """과목·난이도·태그·그림 필터가 WHERE 절과 파라미터 순서에 그대로 반영된다."""
    fake = fake_db(
        {
            COUNT_SELECT: [{"n": 1}],
            QUESTION_SELECT: [question_row()],
            EXAM_EXISTS: [{"?column?": 1}],
        }
    )
    response = client.get(
        "/api/exams/2022-1/questions",
        params={"subjectCode": 3, "difficulty": 2, "figureOnly": "true", "tag": ["정규화", "SQL"]},
    )
    assert response.status_code == 200
    sql, params = fake.single("ORDER BY q.number")
    assert "q.subject_code = %s" in sql
    assert "q.difficulty = %s" in sql
    assert "q.figure_needed" in sql
    assert "t.name = ANY(%s)" in sql
    assert params == ["2022-1", 3, 2, ["정규화", "SQL"], 20, 0]


def test_get_question_not_found(client, fake_db):
    fake_db({})
    response = client.get("/api/questions/없는-문항")
    assert response.status_code == 404
    assert "찾을 수 없습니다" in response.json()["detail"]


@pytest.mark.parametrize("question_id", ["0", "9999", "2022-1-101"])
def test_invalid_ids_do_not_leak_columns(client, fake_db, question_id):
    """존재하지 않는 문항이어도 404 이며 조회 SQL 은 여전히 정답 컬럼을 select 하지 않는다."""
    fake = fake_db({})
    response = client.get(f"/api/questions/{question_id}")
    assert response.status_code == 404
    assert_select_hides_secrets(fake.select_sqls())


def test_openapi_schema_marks_answer_fields_only_on_grading(client):
    """OpenAPI 스키마: 조회 스키마에는 정답 필드가 없고 채점 스키마에만 있다."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schemas = response.json()["components"]["schemas"]

    question_props = set(schemas["QuestionOut"]["properties"])
    assert not question_props & {"answer", "explanation", "choicesAnalysis", "keyPoint"}

    grade_props = set(schemas["GradeResult"]["properties"])
    assert {"answer", "explanation", "keyPoint", "choicesAnalysis"} <= grade_props

    page_props = set(schemas["QuestionPage"]["properties"])
    assert page_props == {"items", "total", "limit", "offset"}
