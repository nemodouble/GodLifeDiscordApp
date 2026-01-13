from __future__ import annotations

from datetime import date, datetime, UTC
from typing import Optional, List, Dict, Any

from db.db import connect_db


async def get_first_checkin_day(user_id: str) -> Optional[str]:
    """유저의 첫 완료 체크인 local_day(YYYY-MM-DD). 없으면 None."""
    conn = await connect_db()
    try:
        cur = await conn.execute(
            """
            SELECT MIN(local_day) AS first_day
            FROM routine_checkin
            WHERE user_id = ? AND checked_at IS NOT NULL AND skipped = 0
            """,
            (user_id,),
        )
        row = await cur.fetchone()
        await cur.close()
        if not row or row["first_day"] is None:
            return None
        return str(row["first_day"])
    finally:
        await conn.close()


async def ensure_default_season(user_id: str, title: str = "현재 시즌") -> int:
    """유저의 시즌이 하나도 없으면 기본 시즌을 만든다.

    마이그레이션 정책(중요):
    - '오늘부터 시작'하지 않는다.
    - 과거 완료 체크인이 있으면, **첫 체크인한 날부터** 시작하는 단일 시즌을 만든다.
    - 완료 체크인이 없으면, fallback으로 오늘부터 시즌을 만든다.

    반환: current season id
    """
    conn = await connect_db()
    try:
        cur = await conn.execute(
            "SELECT id FROM report_season WHERE user_id = ? ORDER BY start_day DESC, id DESC LIMIT 1",
            (user_id,),
        )
        row = await cur.fetchone()
        await cur.close()
        if row:
            return int(row["id"])

        now = datetime.now(UTC).isoformat()

        # 첫 시즌 start_day는 '첫 완료 체크인 day'를 우선 사용
        first_day = await get_first_checkin_day(user_id)
        start_day = first_day or date.today().isoformat()

        cur2 = await conn.execute(
            """
            INSERT INTO report_season(user_id, title, start_day, end_day, created_at, closed_at, is_active)
            VALUES(?, ?, ?, NULL, ?, NULL, 1)
            """,
            (user_id, title, start_day, now),
        )
        await conn.commit()
        return int(cur2.lastrowid)
    finally:
        await conn.close()


async def list_seasons_for_user(user_id: str, limit: int = 12) -> List[Dict[str, Any]]:
    conn = await connect_db()
    try:
        cur = await conn.execute(
            """
            SELECT id, user_id, title, start_day, end_day, created_at, closed_at, is_active
            FROM report_season
            WHERE user_id = ?
            ORDER BY start_day DESC, id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        rows = await cur.fetchall()
        await cur.close()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def get_season(user_id: str, season_id: int) -> Optional[Dict[str, Any]]:
    conn = await connect_db()
    try:
        cur = await conn.execute(
            "SELECT * FROM report_season WHERE user_id = ? AND id = ?",
            (user_id, season_id),
        )
        row = await cur.fetchone()
        await cur.close()
        return dict(row) if row else None
    finally:
        await conn.close()


async def get_current_season(user_id: str) -> Optional[Dict[str, Any]]:
    conn = await connect_db()
    try:
        cur = await conn.execute(
            """
            SELECT * FROM report_season
            WHERE user_id = ?
            ORDER BY start_day DESC, id DESC
            LIMIT 1
            """ ,
            (user_id,),
        )
        row = await cur.fetchone()
        await cur.close()
        return dict(row) if row else None
    finally:
        await conn.close()


async def get_or_create_current_season(user_id: str) -> Dict[str, Any]:
    """현재 시즌(가장 최신 start_day)을 가져오고, 없으면 기본 시즌을 만든 뒤 반환."""
    await ensure_default_season(user_id)
    season = await get_current_season(user_id)
    # ensure_default_season 이후엔 None이면 안 되지만 방어적으로 처리
    if season is None:
        # fallback: 강제로 하나 만들고 다시 조회
        await ensure_default_season(user_id)
        season = await get_current_season(user_id)
    return season or {"id": None, "user_id": user_id, "title": "현재 시즌", "start_day": date.today().isoformat(), "end_day": None}


async def get_season_by_id_for_user(user_id: str, season_id: int) -> Optional[Dict[str, Any]]:
    """유저 소유 검증까지 포함한 시즌 조회(편의 함수)."""
    return await get_season(user_id, season_id)


async def get_last_checkin_day(user_id: str) -> Optional[str]:
    """유저의 마지막 완료 체크인 local_day (YYYY-MM-DD). 없으면 None."""
    conn = await connect_db()
    try:
        cur = await conn.execute(
            """
            SELECT MAX(local_day) AS last_day
            FROM routine_checkin
            WHERE user_id = ? AND checked_at IS NOT NULL AND skipped = 0
            """,
            (user_id,),
        )
        row = await cur.fetchone()
        await cur.close()
        if not row or row["last_day"] is None:
            return None
        return str(row["last_day"])
    finally:
        await conn.close()


async def close_previous_season_to_last_checkin(user_id: str) -> None:
    """직전 시즌의 end_day가 비어있으면, 유저의 마지막 체크인 날로 end_day를 채운다."""
    last_day = await get_last_checkin_day(user_id)
    if not last_day:
        return

    conn = await connect_db()
    try:
        # 최신 시즌(현재 시즌)을 제외한 '직전 시즌'을 찾는다.
        cur = await conn.execute(
            """
            SELECT id
            FROM report_season
            WHERE user_id = ?
            ORDER BY start_day DESC, id DESC
            LIMIT 2
            """,
            (user_id,),
        )
        rows = await cur.fetchall()
        await cur.close()
        if len(rows) < 2:
            return
        prev_id = int(rows[1]["id"])

        await conn.execute(
            """
            UPDATE report_season
               SET end_day = ?
             WHERE id = ? AND user_id = ? AND (end_day IS NULL OR end_day = '')
            """,
            (last_day, prev_id, user_id),
        )
        await conn.commit()
    finally:
        await conn.close()


async def create_new_season(user_id: str, title: str, start_day: str, auto_close_prev: bool = True) -> int:
    """새 시즌을 생성.

    - auto_close_prev=True면, 생성 후 직전 시즌 end_day를 last_checkin_day로 자동 채움.

    반환: new season id
    """
    now = datetime.now(UTC).isoformat()
    conn = await connect_db()
    try:
        cur = await conn.execute(
            """
            INSERT INTO report_season(user_id, title, start_day, end_day, created_at, closed_at, is_active)
            VALUES(?, ?, ?, NULL, ?, NULL, 1)
            """,
            (user_id, title, start_day, now),
        )
        await conn.commit()
        new_id = int(cur.lastrowid)
    finally:
        await conn.close()

    if auto_close_prev:
        # 새 시즌이 만들어졌으니, '직전 시즌'은 이전 레코드가 됨
        await close_previous_season_to_last_checkin(user_id)

    return new_id
