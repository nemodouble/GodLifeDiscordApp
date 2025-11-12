from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from db.db import connect_db


async def add_progress(goal_id: int, user_id: str, delta: int) -> int:
    """goal_progress에 기록을 남기고 goal.current를 갱신한다."""
    now = datetime.utcnow().isoformat()
    conn = await connect_db()
    try:
        # 현재 목표의 값 읽기
        cur = await conn.execute("SELECT current FROM goal WHERE id = ?", (goal_id,))
        row = await cur.fetchone()
        await cur.close()
        if row is None:
            raise ValueError("Goal not found")
        current = row[0]
        new_value = current + delta
        # progress 기록
        cur = await conn.execute(
            "INSERT INTO goal_progress(goal_id, user_id, delta, value_after, created_at) VALUES(?, ?, ?, ?, ?)",
            (goal_id, user_id, delta, new_value, now),
        )
        # goal 업데이트
        await conn.execute("UPDATE goal SET current = ? WHERE id = ?", (new_value, goal_id))
        await conn.commit()
        return cur.lastrowid
    finally:
        await conn.close()


async def list_progress_for_goal(goal_id: int) -> List[dict]:
    conn = await connect_db()
    try:
        cur = await conn.execute("SELECT * FROM goal_progress WHERE goal_id = ? ORDER BY created_at DESC", (goal_id,))
        rows = await cur.fetchall()
        await cur.close()
        return [dict(r) for r in rows]
    finally:
        await conn.close()

