from __future__ import annotations

from datetime import datetime
from typing import Optional

from db.db import connect_db


async def upsert_user_settings(
    user_id: str,
    tz: str = "Asia/Seoul",
    reminder_time: str = "23:00",
    suggest_goals_on_checkin: int | bool = True,
) -> None:
    """user_settings 테이블에 upsert(기본값 포함).

    - 새 레코드가 없으면 INSERT
    - 있으면 tz, reminder_time, suggest_goals_on_checkin 을 갱신
    """
    now = datetime.utcnow().isoformat()
    # bool 로 들어오면 0/1 로 정규화
    suggest_flag = 1 if bool(suggest_goals_on_checkin) else 0

    conn = await connect_db()
    try:
        await conn.execute(
            """
            INSERT INTO user_settings(user_id, tz, reminder_time, suggest_goals_on_checkin, created_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              tz = excluded.tz,
              reminder_time = excluded.reminder_time,
              suggest_goals_on_checkin = excluded.suggest_goals_on_checkin
            """,
            (user_id, tz, reminder_time, suggest_flag, now),
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
        data = dict(row)
        # 없다면 코드 레벨 기본값을 채워줌(마이그레이션 이전 레코드 호환)
        if "suggest_goals_on_checkin" not in data or data["suggest_goals_on_checkin"] is None:
            data["suggest_goals_on_checkin"] = 1
        return data
    finally:
        await conn.close()
