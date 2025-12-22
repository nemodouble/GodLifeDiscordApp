from __future__ import annotations

from datetime import datetime, date
from typing import List, Optional

from db.db import connect_db
from domain.time_utils import local_day, is_applicable_day


async def create_routine(user_id: str, name: str, weekend_mode: str = "weekday", deadline_time: Optional[str] = None, notes: Optional[str] = None, active: int = 1, order_index: Optional[int] = None) -> int:
    now = datetime.utcnow().isoformat()
    conn = await connect_db()
    try:
        # order_index 가 주어지지 않으면, 해당 user_id 의 현재 최대 order_index + 1 로 설정
        if order_index is None:
            cur = await conn.execute("SELECT COALESCE(MAX(order_index), 0) FROM routine WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
            await cur.close()
            max_idx = row[0] if row else 0
            order_index = max_idx + 1

        cur = await conn.execute(
            "INSERT INTO routine(user_id, name, weekend_mode, deadline_time, notes, active, created_at, order_index) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, name, weekend_mode, deadline_time, notes, active, now, order_index),
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
        # 정렬: order_index ASC, fallback 으로 id ASC
        cur = await conn.execute(
            "SELECT * FROM routine WHERE user_id = ? AND active = 1 ORDER BY COALESCE(order_index, id), id",
            (user_id,),
        )
        rows = await cur.fetchall()
        await cur.close()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


def _boolish(v) -> bool:
    try:
        return bool(int(v))
    except Exception:
        return bool(v)


def is_paused_for_day(routine: dict, d: date) -> bool:
    """루틴이 주어진 날짜(d, local_day 기준)에 pause 상태인지 판단.

    정책:
    - paused=1 이면 무기한 pause
    - paused_until 이 설정되어 있으면, d <= paused_until 인 동안 pause
    - 둘 다 없으면 active

    주의: DB에 컬럼이 아직 없을 수도 있으므로 dict.get 기반으로 방어적으로 처리.
    """
    if _boolish(routine.get("paused", 0)):
        return True

    pu = routine.get("paused_until")
    if not pu:
        return False

    try:
        until_d = date.fromisoformat(str(pu))
    except Exception:
        return False

    return d <= until_d


async def set_paused(routine_id: int, paused: bool, paused_until: Optional[str] = None) -> None:
    """루틴의 pause 상태를 설정한다.

    - paused=True: paused=1, paused_until은 그대로 두거나(옵션) 함께 세팅 가능
    - paused=False: paused=0, paused_until=NULL (해제 시 기간 pause도 함께 해제)

    paused_until: 'YYYY-MM-DD' 또는 None
    """
    fields = {}
    if paused:
        fields["paused"] = 1
        if paused_until is not None:
            fields["paused_until"] = paused_until
    else:
        fields["paused"] = 0
        fields["paused_until"] = None

    await update_routine(routine_id, **fields)


async def toggle_paused(routine_id: int) -> bool:
    """루틴 pause 토글. 새 paused 상태(True=paused)를 반환."""
    r = await get_routine(routine_id)
    if not r:
        raise ValueError(f"routine not found: {routine_id}")
    new_paused = not _boolish(r.get("paused", 0))
    await set_paused(routine_id, new_paused)
    return new_paused


async def routines_applicable_for_date(user_id: str, d: date) -> List[dict]:
    """주어진 날짜(local_day) 기준으로 적용 가능한(주말모드에 맞는) 활성 루틴 목록을 반환.

    주의: pause 여부는 여기서 제외하지 않고, 호출자(체크인 UI/스케줄러/통계)가
    정책에 맞게 별도로 처리하도록 둔다.
    """
    conn = await connect_db()
    try:
        cur = await conn.execute(
            "SELECT * FROM routine WHERE user_id = ? AND active = 1 ORDER BY COALESCE(order_index, id), id",
            (user_id,),
        )
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
