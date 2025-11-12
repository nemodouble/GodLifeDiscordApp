from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from db.db import connect_db


async def create_goal(user_id: str, title: str, period: str, target: int, deadline: Optional[str] = None, carry_over: int = 0) -> int:
    now = datetime.utcnow().isoformat()
    conn = await connect_db()
    try:
        cur = await conn.execute(
            "INSERT INTO goal(user_id, title, period, target, current, carry_over, deadline, active, created_at) VALUES(?, ?, ?, ?, 0, ?, ?, 1, ?)",
            (user_id, title, period, target, carry_over, deadline, now),
        )
        await conn.commit()
        return cur.lastrowid
    finally:
        await conn.close()


async def get_goal(goal_id: int) -> Optional[dict]:
    conn = await connect_db()
    try:
        cur = await conn.execute("SELECT * FROM goal WHERE id = ?", (goal_id,))
        row = await cur.fetchone()
        await cur.close()
        return dict(row) if row else None
    finally:
        await conn.close()


async def update_goal(goal_id: int, **fields) -> None:
    if not fields:
        return
    keys = ", ".join(f"{k} = ?" for k in fields.keys())
    vals = list(fields.values())
    vals.append(goal_id)
    conn = await connect_db()
    try:
        await conn.execute(f"UPDATE goal SET {keys} WHERE id = ?", vals)
        await conn.commit()
    finally:
        await conn.close()


async def delete_goal(goal_id: int) -> None:
    conn = await connect_db()
    try:
        await conn.execute("DELETE FROM goal WHERE id = ?", (goal_id,))
        await conn.commit()
    finally:
        await conn.close()


async def list_active_goals_for_user(user_id: str) -> List[dict]:
    conn = await connect_db()
    try:
        cur = await conn.execute("SELECT * FROM goal WHERE user_id = ? AND active = 1", (user_id,))
        rows = await cur.fetchall()
        await cur.close()
        return [dict(r) for r in rows]
    finally:
        await conn.close()

