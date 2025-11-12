from __future__ import annotations

from datetime import datetime, date
from typing import List, Optional

from db.db import connect_db
from domain.time_utils import local_day, is_applicable_day


async def create_routine(user_id: str, name: str, weekend_mode: str = "weekday", deadline_time: Optional[str] = None, notes: Optional[str] = None, active: int = 1) -> int:
    now = datetime.utcnow().isoformat()
    conn = await connect_db()
    try:
        cur = await conn.execute(
            "INSERT INTO routine(user_id, name, weekend_mode, deadline_time, notes, active, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
            (user_id, name, weekend_mode, deadline_time, notes, active, now),
        )
        await conn.commit()
        return cur.lastrowid
    finally:
        await conn.close()


async def get_routine(routine_id: int) -> Optional[dict]:
    conn = await connect_db()
    try:
        cur = await conn.execute("SELECT * FROM routine WHERE id = ?", (routine_id,))
        row = await cur.fetchone()
        await cur.close()
        return dict(row) if row else None
    finally:
        await conn.close()


async def update_routine(routine_id: int, **fields) -> None:
    if not fields:
        return
    keys = ", ".join(f"{k} = ?" for k in fields.keys())
    vals = list(fields.values())
    vals.append(routine_id)
    conn = await connect_db()
    try:
        await conn.execute(f"UPDATE routine SET {keys} WHERE id = ?", vals)
        await conn.commit()
    finally:
        await conn.close()


async def delete_routine(routine_id: int) -> None:
    conn = await connect_db()
    try:
        await conn.execute("DELETE FROM routine WHERE id = ?", (routine_id,))
        await conn.commit()
    finally:
        await conn.close()


async def list_active_routines_for_user(user_id: str) -> List[dict]:
    conn = await connect_db()
    try:
        cur = await conn.execute("SELECT * FROM routine WHERE user_id = ? AND active = 1", (user_id,))
        rows = await cur.fetchall()
        await cur.close()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def routines_applicable_for_date(user_id: str, d: date) -> List[dict]:
    """주어진 날짜(local_day) 기준으로 적용 가능한(주말모드에 맞는) 활성 루틴 목록을 반환한다."""
    conn = await connect_db()
    try:
        cur = await conn.execute("SELECT * FROM routine WHERE user_id = ? AND active = 1", (user_id,))
        rows = await cur.fetchall()
        await cur.close()
        result = []
        for r in rows:
            if is_applicable_day(r["weekend_mode"], d):
                result.append(dict(r))
        return result
    finally:
        await conn.close()


async def prepare_checkin_for_date(user_id: str, dt: datetime) -> List[dict]:
    """주어진 시각(dt)의 local_day에 대해 체크인이 준비되어야 하는 루틴 목록 반환."""
    ld = local_day(dt)
    return await routines_applicable_for_date(user_id, ld)

