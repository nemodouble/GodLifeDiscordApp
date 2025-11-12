import asyncio
import sys
from pathlib import Path

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import datetime
from cogs.scheduler import SchedulerCog
from db.db import connect_db

async def main():
    # create scheduler cog with dummy bot (None is fine for compose function)
    cog = SchedulerCog(bot=None)

    # collect user ids from user_settings or routine
    conn = await connect_db()
    try:
        cur = await conn.execute("SELECT user_id FROM user_settings")
        rows = await cur.fetchall()
        await cur.close()
        if rows:
            users = [r[0] for r in rows]
        else:
            cur = await conn.execute("SELECT DISTINCT user_id FROM routine")
            rows = await cur.fetchall()
            await cur.close()
            users = [r[0] for r in rows]
    finally:
        await conn.close()

    print('Found users:', users)

    # use date 2025-11-12 as requested
    test_dt = datetime(2025,11,12,12,0)

    from repos import routine_repo
    for uid in users:
        routines = await routine_repo.prepare_checkin_for_date(uid, test_dt)
        msg = await cog._compose_reminder_message(uid, test_dt.date(), routines)
        print(f"--- user {uid} message ---")
        print(msg)

if __name__ == '__main__':
    asyncio.run(main())
