from __future__ import annotations

from datetime import date
from typing import Optional, List

from db.db import connect_db


async def create_exemption(user_id: str, start_day: date | str, end_day: date | str, reason: Optional[str] = None) -> int:
    sd = start_day.isoformat() if isinstance(start_day, date) else start_day
    ed = end_day.isoformat() if isinstance(end_day, date) else end_day
    conn = await connect_db()
    try:
        cur = await conn.execute(
            "INSERT INTO exemption(user_id, start_day, end_day, reason) VALUES(?, ?, ?, ?)",
            (user_id, sd, ed, reason),
        )
        await conn.commit()
        return cur.lastrowid
    finally:
        await conn.close()


async def get_exemption(exemption_id: int) -> Optional[dict]:
    conn = await connect_db()
    try:
        cur = await conn.execute("SELECT * FROM exemption WHERE id = ?", (exemption_id,))
        row = await cur.fetchone()
        await cur.close()
        return dict(row) if row else None
    finally:
        await conn.close()


async def list_exemptions_for_user(user_id: str) -> List[dict]:
    conn = await connect_db()
    try:
        cur = await conn.execute("SELECT * FROM exemption WHERE user_id = ? ORDER BY start_day DESC", (user_id,))
        rows = await cur.fetchall()
        await cur.close()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def delete_exemption(exemption_id: int) -> None:
    conn = await connect_db()
    try:
        await conn.execute("DELETE FROM exemption WHERE id = ?", (exemption_id,))
        await conn.commit()
    finally:
        await conn.close()

