"""시즌 기능 스모크 테스트(로컬 실행용).

목표:
- report_season 테이블이 존재
- 시즌이 비어있는 유저의 첫 시즌은 '오늘'이 아니라 **첫 완료 체크인(local_day)** 부터 시작한다
- 새 시즌 생성 시, 직전 시즌 end_day가 유저의 마지막 완료 체크인 local_day로 자동 등록

주의:
- 개발 DB(data/database.db)에 테스트 데이터를 잠깐 넣었다가 정리합니다.
"""

from __future__ import annotations

import asyncio
from datetime import date
import sys
from pathlib import Path

# scripts/ 아래에서 실행해도 import가 되도록 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from db.db import init_db, connect_db
from repos import report_season_repo


async def main() -> None:
    await init_db()

    user_id = "season_test_user"

    # 테스트 유저 데이터 정리
    conn = await connect_db()
    try:
        await conn.execute("DELETE FROM routine_checkin WHERE user_id = ?", (user_id,))
        await conn.execute("DELETE FROM report_season WHERE user_id = ?", (user_id,))
        await conn.commit()

        # 첫 체크인 기록을 만든 뒤, 시즌을 생성하면 start_day가 첫 체크인 day여야 한다
        first_day = date(2026, 1, 5).isoformat()
        last_day = date(2026, 1, 10).isoformat()
        await conn.execute(
            """
            INSERT INTO routine_checkin(routine_id, user_id, local_day, checked_at, undone_at, skipped, skip_reason)
            VALUES(1, ?, ?, 'done', NULL, 0, NULL)
            """,
            (user_id, first_day),
        )
        await conn.execute(
            """
            INSERT INTO routine_checkin(routine_id, user_id, local_day, checked_at, undone_at, skipped, skip_reason)
            VALUES(1, ?, ?, 'done', NULL, 0, NULL)
            """,
            (user_id, last_day),
        )
        await conn.commit()

        # 기본 시즌 1개 생성(마이그레이션 규칙 적용)
        sid1 = await report_season_repo.ensure_default_season(user_id, title="시즌1")
        s1 = await report_season_repo.get_season(user_id, sid1)
        assert s1 is not None
        assert s1.get("start_day") == first_day, ("expected start_day", first_day, "got", s1.get("start_day"))

        # 새 시즌 생성 -> 직전 시즌(시즌1)의 end_day가 last_day로 채워져야 함
        sid2 = await report_season_repo.create_new_season(user_id, title="시즌2", start_day=date(2026, 1, 14).isoformat())

        s1 = await report_season_repo.get_season(user_id, sid1)
        s2 = await report_season_repo.get_season(user_id, sid2)

        assert s1 is not None and s2 is not None
        assert s1.get("end_day") == last_day, ("expected end_day", last_day, "got", s1.get("end_day"))

        print("OK: default season start_day uses first checkin day")
        print("OK: prev season end_day auto-closed to last checkin day")
        print("season1:", s1)
        print("season2:", s2)

    finally:
        # 테스트 유저 데이터 정리
        try:
            await conn.execute("DELETE FROM routine_checkin WHERE user_id = ?", (user_id,))
            await conn.execute("DELETE FROM report_season WHERE user_id = ?", (user_id,))
            await conn.commit()
        finally:
            await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
