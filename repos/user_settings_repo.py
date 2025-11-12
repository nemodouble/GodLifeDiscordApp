from __future__ import annotations

from datetime import datetime
from typing import Optional

from db.db import connect_db


async def upsert_user_settings(user_id: str, tz: str = "Asia/Seoul", reminder_time: str = "08:00") -> None:
    """user_settings 테이블에 upsert(기본값 포함).

    - 새 레코드가 없으면 INSERT
    - 있으면 tz, reminder_time을 갱신
    """
    now = datetime.utcnow().isoformat()
    conn = await connect_db()
    try:
        await conn.execute(
            """
            INSERT INTO user_settings(user_id, tz, reminder_time, created_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              tz = excluded.tz,
              reminder_time = excluded.reminder_time
            """,
            (user_id, tz, reminder_time, now),
        )
        await conn.commit()
    finally:
        await conn.close()


async def get_user_settings(user_id: str) -> Optional[dict]:
    conn = await connect_db()
    try:
        cur = await conn.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        await cur.close()
        if row is None:
            return None
        return dict(row)
    finally:
        await conn.close()

