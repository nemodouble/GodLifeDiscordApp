"""시즌 start_day 보정 마이그레이션 스모크 테스트.

시나리오:
- 어떤 유저가 시즌 기능 도입 초기에 '오늘(date.today())'로 start_day가 찍힌 시즌 1개를 이미 가진 상태
- 그런데 실제 완료 체크인은 더 과거에 존재

기대:
- init_db() 실행 시 start_day가 첫 완료 체크인 day로 자동 보정된다.

주의:
- 개발 DB에 데이터가 잠깐 들어갔다가 정리됩니다.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from db.db import init_db, connect_db


async def main() -> None:
    user_id = "season_fix_test_user"
    today = date.today().isoformat()

    # clean
    db = await connect_db()
    try:
        await db.execute("DELETE FROM routine_checkin WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM report_season WHERE user_id = ?", (user_id,))
        await db.commit()

        # create a 'bad' season: start_day=today
        await db.execute(
            "INSERT INTO report_season(user_id, title, start_day, end_day, created_at, closed_at, is_active) VALUES(?, 'BAD', ?, NULL, 'now', NULL, 1)",
            (user_id, today),
        )
        # and earlier checkin exists
        first_day = "2026-01-01"
        await db.execute(
            "INSERT INTO routine_checkin(routine_id, user_id, local_day, checked_at, undone_at, skipped, skip_reason) VALUES(1, ?, ?, 'done', NULL, 0, NULL)",
            (user_id, first_day),
        )
        await db.commit()
    finally:
        await db.close()

    # run migration
    await init_db()

    # verify
    db = await connect_db()
    try:
        cur = await db.execute("SELECT start_day FROM report_season WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,))
        row = await cur.fetchone()
        await cur.close()
        assert row is not None
        got = str(row[0])
        assert got == first_day, ("expected", first_day, "got", got)
        print("OK: start_day auto-fixed", got)
    finally:
        try:
            await db.execute("DELETE FROM routine_checkin WHERE user_id = ?", (user_id,))
            await db.execute("DELETE FROM report_season WHERE user_id = ?", (user_id,))
            await db.commit()
        finally:
            await db.close()


if __name__ == "__main__":
    asyncio.run(main())

