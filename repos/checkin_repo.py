from __future__ import annotations

from datetime import datetime, date
from typing import Optional, List, Union

from db.db import connect_db


def _iso_date(d: Union[date, str]) -> str:
    if isinstance(d, date):
        return d.isoformat()
    return d


async def upsert_checkin_done(routine_id: int, user_id: str, local_day: Union[date, str]) -> None:
    """체크인 완료(또는 idempotent 업서트).

    동일 (routine_id, local_day)에 대해 여러 번 실행해도 안전하게 최신 checked_at으로 갱신됩니다.
    """
    ld = _iso_date(local_day)
    now = datetime.utcnow().isoformat()
    conn = await connect_db()
    try:
        await conn.execute(
            """
            INSERT INTO routine_checkin(routine_id, user_id, local_day, checked_at, undone_at, skipped, skip_reason)
            VALUES(?, ?, ?, ?, NULL, 0, NULL)
            ON CONFLICT(routine_id, local_day) DO UPDATE SET
              checked_at = excluded.checked_at,
              undone_at = NULL,
              skipped = 0,
              skip_reason = NULL
            """,
            (routine_id, user_id, ld, now),
        )
        await conn.commit()
    finally:
        await conn.close()


async def undo_checkin(routine_id: int, local_day: Union[date, str]) -> None:
    """체크인을 취소(undo). checked_at을 지우고 undone_at을 기록한다."""
    ld = _iso_date(local_day)
    now = datetime.utcnow().isoformat()
    conn = await connect_db()
    try:
        await conn.execute(
            "UPDATE routine_checkin SET checked_at = NULL, undone_at = ? WHERE routine_id = ? AND local_day = ?",
            (now, routine_id, ld),
        )
        await conn.commit()
    finally:
        await conn.close()


async def skip_checkin(routine_id: int, user_id: str, local_day: Union[date, str], reason: Optional[str] = None) -> None:
    """해당 날짜 체크인을 스킵으로 표시(스킵은 idempotent)."""
    ld = _iso_date(local_day)
    datetime.utcnow().isoformat()
    conn = await connect_db()
    try:
        await conn.execute(
            """
            INSERT INTO routine_checkin(routine_id, user_id, local_day, checked_at, undone_at, skipped, skip_reason)
            VALUES(?, ?, ?, NULL, NULL, 1, ?)
            ON CONFLICT(routine_id, local_day) DO UPDATE SET
              skipped = 1,
              skip_reason = excluded.skip_reason,
              checked_at = NULL,
              undone_at = NULL
            """,
            (routine_id, user_id, ld, reason),
        )
        await conn.commit()
    finally:
        await conn.close()


async def get_checkin(routine_id: int, local_day: Union[date, str]) -> Optional[dict]:
    ld = _iso_date(local_day)
    conn = await connect_db()
    try:
        cur = await conn.execute("SELECT * FROM routine_checkin WHERE routine_id = ? AND local_day = ?", (routine_id, ld))
        row = await cur.fetchone()
        await cur.close()
        return dict(row) if row else None
    finally:
        await conn.close()


async def list_checkins_for_user_day(user_id: str, local_day: Union[date, str]) -> List[dict]:
    ld = _iso_date(local_day)
    conn = await connect_db()
    try:
        cur = await conn.execute("SELECT * FROM routine_checkin WHERE user_id = ? AND local_day = ?", (user_id, ld))
        rows = await cur.fetchall()
        await cur.close()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def clear_checkin(routine_id: int, local_day: Union[date, str]) -> None:
    """체크인 상태를 초기화(미달성 상태로 설정).

    기존 레코드가 있으면 checked_at, undone_at, skipped, skip_reason을 NULL/0으로 갱신합니다.
    """
    ld = _iso_date(local_day)
    conn = await connect_db()
    try:
        await conn.execute(
            "UPDATE routine_checkin SET checked_at = NULL, undone_at = NULL, skipped = 0, skip_reason = NULL WHERE routine_id = ? AND local_day = ?",
            (routine_id, ld),
        )
        await conn.commit()
    finally:
        await conn.close()
