"""태그 목록(필터용)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ..deps import Conn
from ..schemas import TagOut

router = APIRouter(prefix="/api", tags=["tags"])


@router.get("/tags", response_model=list[TagOut], summary="태그 목록")
def list_tags(
    conn: Conn,
    q: Annotated[str | None, Query(description="이름 부분일치(대소문자 무시)")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
):
    """문항이 많은 순. q 로 이름을 걸러낸다."""
    params: list = []
    where = ""
    if q:
        where = " WHERE t.name ILIKE %s"
        params.append(f"%{q}%")
    sql = f"""
    SELECT t.id, t.name, count(qt.question_id)::int AS question_count
      FROM ipe.tag t
      LEFT JOIN ipe.question_tag qt ON qt.tag_id = t.id
      {where}
     GROUP BY t.id, t.name
     ORDER BY question_count DESC, t.name
     LIMIT %s
    """
    return conn.execute(sql, [*params, limit]).fetchall()
