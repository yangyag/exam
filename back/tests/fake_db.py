"""DB 없이 라우터를 돌리기 위한 가짜 psycopg 커넥션.

규칙(rules)은 "SQL 안에 이 조각이 있으면 이 행들을 돌려준다"는 식이다.
정적 목록을 주거나, (sql, params) 를 받아 행을 만드는 함수를 줄 수 있다.
"""
from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterable
from typing import Any

Row = dict[str, Any]
RowSource = list[Row] | Callable[[str, Any], list[Row]]


def normalize_sql(sql: str) -> str:
    """공백 차이를 없애 조각 매칭이 흔들리지 않게 한다."""
    return " ".join(sql.split())


class FakeResult:
    """psycopg Cursor 의 fetchone/fetchall 만 흉내낸다."""

    def __init__(self, rows: Iterable[Row]):
        self.rows = list(rows)

    def fetchone(self) -> Row | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[Row]:
        return list(self.rows)


class FakeConnection:
    def __init__(self, rules: dict[str, RowSource] | None = None):
        self.rules = dict(rules or {})
        self.calls: list[tuple[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> FakeResult:
        normalized = normalize_sql(sql)
        self.calls.append((normalized, params))
        for fragment, source in self.rules.items():
            if fragment in normalized:
                rows = source(normalized, params) if callable(source) else source
                return FakeResult(rows)
        return FakeResult([])

    def transaction(self):
        return contextlib.nullcontext()

    def executed(self, fragment: str) -> list[tuple[str, Any]]:
        """지금까지 실행된 호출 중 SQL 에 조각이 들어간 것만 돌려준다."""
        return [(sql, params) for sql, params in self.calls if fragment in sql]

    def select_sqls(self) -> list[str]:
        return [sql for sql, _ in self.calls if sql.upper().startswith("SELECT")]

    def single(self, fragment: str) -> tuple[str, Any]:
        """조각에 맞는 호출이 정확히 하나일 때 그 (sql, params) 를 돌려준다."""
        found = self.executed(fragment)
        assert len(found) == 1, f"{fragment!r} 에 맞는 호출이 {len(found)}건이다: {found}"
        return found[0]
