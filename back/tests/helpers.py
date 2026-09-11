"""테스트 공용 검사 도구.

정답·해설 누출 검사는 "응답 JSON 어디에도 정답 필드가 없어야 한다"는 규칙을 재귀적으로 확인한다.
"""
from __future__ import annotations

import re
from typing import Any

# 조회 응답에 절대 나오면 안 되는 키(camelCase·snake_case 모두).
SECRET_KEYS = frozenset(
    {
        "answer",
        "explanation",
        "choicesAnalysis",
        "choices_analysis",
        "keyPoint",
        "key_point",
    }
)

# 조회 SELECT 에 절대 들어가면 안 되는 컬럼. \b 는 last_answered_at 같은 이름을 걸러내기 위함이다.
FORBIDDEN_COLUMN_PATTERN = re.compile(
    r"\b(?:q\.)?answer\b|\bexplanation\b|\bis_correct\b|\bwhy\b|\bkey_point\b"
)


def collect_keys(value: Any) -> set[str]:
    """JSON 구조(dict/list) 안의 모든 키를 모은다."""
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(key)
            keys |= collect_keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= collect_keys(item)
    return keys


def assert_no_answer_leak(payload: Any) -> None:
    """응답 어디에도 정답·해설·보기별 해설 키가 없는지 확인한다."""
    leaked = collect_keys(payload) & SECRET_KEYS
    assert not leaked, f"조회 응답에 정답·해설 필드가 샜다: {sorted(leaked)}"


def assert_select_hides_secrets(select_sqls: list[str]) -> None:
    """조회 SQL 이 정답·해설 컬럼을 select 하지 않는지 확인한다."""
    for sql in select_sqls:
        match = FORBIDDEN_COLUMN_PATTERN.search(sql)
        assert match is None, f"조회 SQL 에 금지 컬럼이 있다({match.group(0)}): {sql}"
