from __future__ import annotations

import sys
from pathlib import Path
# 프로젝트 루트 경로를 sys.path에 추가하여 `from db.db import ...` 같은 sibling 패키지 import가 동작하도록 함
sys.path.append(str(Path(__file__).resolve().parents[1]))

import asyncio
from datetime import date

from db.db import init_db
from domain.time_utils import now_kst, local_day, is_exempt

from repos.user_settings_repo import upsert_user_settings, get_user_settings
from repos.routine_repo import create_routine, list_active_routines_for_user, prepare_checkin_for_date
from repos.checkin_repo import upsert_checkin_done, get_checkin, undo_checkin, skip_checkin, list_checkins_for_user_day
from repos.goal_repo import create_goal, list_active_goals_for_user
from repos.progress_repo import add_progress, list_progress_for_goal
from repos.exemption_repo import create_exemption, list_exemptions_for_user


async def main() -> None:
    await init_db()

    user_id = "smoke_user"

    # User settings
    await upsert_user_settings(user_id)
    us = await get_user_settings(user_id)
    print("user_settings:", us)

    # Routine
    rid = await create_routine(user_id, "smoke routine")
    routines = await list_active_routines_for_user(user_id)
    print("routines:", routines)

    # Prepare checkin and operate checkins
    dt = now_kst()
    ld = local_day(dt)
    prep = await prepare_checkin_for_date(user_id, dt)
    print("prepare_checkin:", prep)

    await upsert_checkin_done(rid, user_id, ld)
    c = await get_checkin(rid, ld)
    print("checkin after done:", c)

    await undo_checkin(rid, ld)
    c2 = await get_checkin(rid, ld)
    print("checkin after undo:", c2)

    await skip_checkin(rid, user_id, ld, "test skip")
    c3 = await get_checkin(rid, ld)
    print("checkin after skip:", c3)

    # Goal & progress
    gid = await create_goal(user_id, "smoke goal", "daily", 5)
    await add_progress(gid, user_id, 2)
    prog = await list_progress_for_goal(gid)
    print("progress:", prog)

    # Exemption
    ex_id = await create_exemption(user_id, ld, ld, "smoke exemption")
    exs = await list_exemptions_for_user(user_id)
    print("exemptions:", exs)

    is_ex = await is_exempt(user_id, ld)
    print("is_exempt:", is_ex)


if __name__ == "__main__":
    asyncio.run(main())
