from __future__ import annotations

import asyncio
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

from db.db import init_db, connect_db
from domain.time_utils import (
    KST,
    now_kst,
    local_day,
    is_exempt,
    is_valid_day,
)


async def main() -> None:
    await init_db()

    user_id = "test_user"

    # 테스트에 사용할 날짜: 오늘 KST 기준 local_day
    now = now_kst()
    today_local = local_day(now)

    # 면책 기간: 오늘-1 ~ 오늘+1
    start = today_local - timedelta(days=1)
    end = today_local + timedelta(days=1)

    conn = await connect_db()
    try:
        # 기존 테스트 데이터 제거
        await conn.execute("DELETE FROM exemption WHERE user_id = ?", (user_id,))
        # 면책 삽입
        await conn.execute(
            "INSERT INTO exemption (user_id, start_day, end_day, reason) VALUES (?, ?, ?, ?)",
            (user_id, start.isoformat(), end.isoformat(), "smoke test"),
        )
        await conn.commit()

        # 검사: 범위 내/외
        print("now_kst() =", now)
        print("today_local =", today_local, "(local_day)")
        print("exemption range =", start.isoformat(), "~", end.isoformat())

        for delta in (-1, 0, 1, 2):
            d = today_local + timedelta(days=delta)
            ex = await is_exempt(user_id, d)
            print(f"is_exempt({d}) =", ex)

        # is_valid_day 테스트 (weekend_mode 변형)
        for mode in ("weekday", "weekend", "all"):
            valid = await is_valid_day(user_id, mode, today_local)
            print(f"is_valid_day(user={user_id}, mode={mode}, date={today_local}) =", valid)

    finally:
        # 테스트 데이터 정리
        await conn.execute("DELETE FROM exemption WHERE user_id = ?", (user_id,))
        await conn.commit()
        await conn.close()

    # 04:00 경계 스모크 테스트
    dt1 = datetime(2025, 11, 11, 3, 59, tzinfo=KST)
    dt2 = datetime(2025, 11, 11, 4, 0, tzinfo=KST)
    print("local_day(2025-11-11 03:59 KST) =", local_day(dt1))
    print("local_day(2025-11-11 04:00 KST) =", local_day(dt2))


if __name__ == "__main__":
    asyncio.run(main())

