# New scheduler cog implementing daily prompts and deadline reminders (MVP)
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Set, Tuple, Optional
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from db.db import connect_db
from repos import user_settings_repo, routine_repo, checkin_repo
from domain.time_utils import now_kst, local_day, is_valid_day, KST


class SchedulerCog(commands.Cog):
    """스케줄러 코그 (MVP)

    - 부팅 시 schedule_today()를 호출해 오늘의 트리거를 예약
    - 5분 보정 루프를 돌며 지나간(놓친) 트리거를 보정 실행
    - 메모리 sent_keys 세트로 중복 송신을 방지

    키 형식: (user_id, local_day_iso, kind, optional_routine_id)
    kind: 'daily_prompt' | 'deadline_reminder'
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sent_keys: Set[Tuple[str, str, str, Optional[int]]] = set()
        self._correction_task: Optional[asyncio.Task] = None
        self._startup_task: Optional[asyncio.Task] = None

    async def cog_load(self) -> None:
        # 봇이 로드될 때 schedule_today를 시작
        # (discord.py v2 스타일 hook; on_ready에서도 중복 실행 방지 필요할 수 있음)
        # 비동기 초기화는 별도 태스크로 실행
        self._startup_task = asyncio.create_task(self.schedule_today())

    async def cog_unload(self) -> None:
        if self._correction_task:
            self._correction_task.cancel()
        if self._startup_task:
            self._startup_task.cancel()

    async def schedule_today(self) -> None:
        """오늘의 모든 사용자를 스캔해 트리거를 예약하고 보정 루프를 시작."""
        try:
            print("Scheduler: schedule_today 시작")
            # 봇이 ready 상태가 될 때까지 기다립니다. (연결 전 DM 전송 등 실패 방지)
            if not getattr(self.bot, 'is_ready', lambda: False)():
                try:
                    print("Scheduler: waiting until bot ready...")
                    await self.bot.wait_until_ready()
                    print("Scheduler: bot ready")
                except Exception:
                    # wait_until_ready may raise if bot is closed; ignore and continue
                    pass

            now = now_kst()
            # 스케줄링 대상 사용자 목록 조회
            conn = await connect_db()
            try:
                cur = await conn.execute("SELECT user_id, tz, reminder_time FROM user_settings")
                users = await cur.fetchall()
                await cur.close()

                # fallback: user_settings가 비어있으면 routine 테이블에서 사용자 목록을 추출
                if not users:
                    cur = await conn.execute("SELECT DISTINCT user_id FROM routine")
                    rows = await cur.fetchall()
                    await cur.close()
                    users = [(r[0], 'Asia/Seoul', '23:00') for r in rows]
            finally:
                await conn.close()

            print(f"Scheduler: found {len(users) if users else 0} users for scheduling")

            for u in users:
                user_id = str(u[0])
                tz_name = u[1] or "Asia/Seoul"
                reminder_time = u[2] or "23:00"
                # daily prompt
                when_dt = self._make_when_dt_for_date(now, tz_name, reminder_time)
                print(f"Scheduler: user={user_id} tz={tz_name} reminder_time={reminder_time} -> when_dt={when_dt.isoformat()}")
                if when_dt > now:
                    asyncio.create_task(self._daily_prompt_task(user_id, when_dt))
                    print(f"Scheduler: scheduled daily_prompt for user={user_id} at {when_dt.isoformat()}")
                else:
                    print(f"Scheduler: skipping daily_prompt (time already passed) for user={user_id} at {when_dt.isoformat()}")
                # deadline reminders: 모든 활성 루틴 조회
                try:
                    routines = await routine_repo.list_active_routines_for_user(user_id)
                except Exception as e:
                    print("scheduler: routine list error:", e)
                    routines = []

                for r in routines:
                    # deadline_time 우선, 없으면 user reminder_time
                    dt_str = r.get("deadline_time") or reminder_time
                    when_dt_r = self._make_when_dt_for_date(now, tz_name, dt_str)
                    if when_dt_r > now:
                        asyncio.create_task(self._deadline_task(user_id, r["id"], when_dt_r))
                        print(f"Scheduler: scheduled deadline_reminder for user={user_id} routine={r['id']} at {when_dt_r.isoformat()}")
                    else:
                        print(f"Scheduler: skipping deadline_reminder (time passed) for user={user_id} routine={r['id']} at {when_dt_r.isoformat()}")

            # correction loop 시작
            self._correction_task = asyncio.create_task(self._correction_loop())

            # 초기 보정 즉시 수행(부팅 직후 놓친 트리거 보정)
            await self._run_correction_once()

        except Exception as e:
            print("schedule_today 에러:", e)

    def _make_when_dt_for_date(self, now_kst_dt: datetime, tz_name: str, time_str: str) -> datetime:
        """사용자 tz/time_str으로 오늘의 datetime을 만들고 KST로 변환하여 반환한다."""
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = KST
        # 현재 시각을 사용자 tz로 변환하여 오늘 날짜 결정
        now_user = now_kst_dt.astimezone(tz)
        h, m = 8, 0
        try:
            parts = time_str.split(":")
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
        except Exception:
            pass
        dt_user = datetime(now_user.year, now_user.month, now_user.day, h, m, tzinfo=tz)
        # KST로 변환
        return dt_user.astimezone(KST)

    async def _daily_prompt_task(self, user_id: str, when_dt: datetime) -> None:
        # 지정 시각까지 대기
        now = now_kst()
        delay = (when_dt - now).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)
        # 멱등키 체크
        ld = local_day(now_kst())
        key = (user_id, ld.isoformat(), "daily_prompt", None)
        if key in self.sent_keys:
            return
        # 루틴 존재 여부 확인 (is_valid_day 필터 포함)
        try:
            routines = await routine_repo.prepare_checkin_for_date(user_id, now_kst())
        except Exception as e:
            print("daily_prompt: prepare_checkin_for_date error:", e)
            return
        valid = []
        for r in routines:
            try:
                if await is_valid_day(user_id, r.get("weekend_mode", "weekday"), ld):
                    # pause 루틴은 알림 대상에서 제외
                    if routine_repo.is_paused_for_day(r, ld):
                        continue
                    valid.append(r)
            except Exception as e:
                print("daily_prompt: is_valid_day error:", e)
                continue
        # Compose message listing incomplete routines (or an all-done message)
        try:
            content = await self._compose_reminder_message(user_id, ld, valid)
            await self._safe_send_dm(user_id, content)
        except Exception as e:
            print("daily_prompt: message compose/send error:", e)
            return
        self.sent_keys.add(key)

    async def _deadline_task(self, user_id: str, routine_id: int, when_dt: datetime) -> None:
        now = now_kst()
        delay = (when_dt - now).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)
        ld = local_day(now_kst())
        key = (user_id, ld.isoformat(), "deadline_reminder", routine_id)
        if key in self.sent_keys:
            return
        # 확인: 해당 루틴이 유효한 날인지
        try:
            routine = await routine_repo.get_routine(routine_id)
        except Exception as e:
            print("deadline_task: get_routine error:", e)
            return
        if routine is None:
            return
        # pause 루틴은 deadline 리마인더 대상에서 제외
        if routine_repo.is_paused_for_day(routine, ld):
            self.sent_keys.add(key)
            return
        try:
            if not await is_valid_day(user_id, routine.get("weekend_mode", "weekday"), ld):
                self.sent_keys.add(key)
                return
        except Exception as e:
            print("deadline_task: is_valid_day error:", e)
            return
        # 체크인 상태 확인: 미완료면 DM
        try:
            ci = await checkin_repo.get_checkin(routine_id, ld)
        except Exception as e:
            print("deadline_task: get_checkin error:", e)
            return
        # 조건: checked_at is None and skipped == 0
        if ci and (ci.get("checked_at") or ci.get("skipped")):
            self.sent_keys.add(key)
            return
        # 미완료: DM 보내기 (전체 미완성 목록으로 구성)
        try:
            # reuse compose logic to list incomplete routines for the day
            routines = await routine_repo.prepare_checkin_for_date(user_id, now_kst())
            valid = []
            for r in routines:
                try:
                    if await is_valid_day(user_id, r.get("weekend_mode", "weekday"), ld):
                        if routine_repo.is_paused_for_day(r, ld):
                            continue
                        valid.append(r)
                except Exception:
                    continue
            content = await self._compose_reminder_message(user_id, ld, valid)
            await self._safe_send_dm(user_id, content)
        except Exception as e:
            print("deadline_task: compose/send error:", e)
            return
        self.sent_keys.add(key)

    async def _compose_reminder_message(self, user_id: str, ld_date, routines_list: list) -> str:
        """주어진 날짜(ld_date)와 적용 루틴 목록(routines_list)에서 미완료 루틴을 찾아 메시지를 반환합니다.

        routines_list: list of routine dicts (may be empty)
        """
        # ld_date는 date 객체
        date_str = ld_date.isoformat() if hasattr(ld_date, 'isoformat') else str(ld_date)

        # determine particle based on last digit rule: 1,3,6,7,8,0 -> '은', others -> '는'
        last_char = date_str[-1] if date_str else ''
        particle = '은' if last_char in {'1','3','6','7','8','0'} else '는'

        # If no routines apply at all, treat as all done
        if not routines_list:
            return f"{date_str}{particle} 모든 루틴을 달성하셨어요! 잘하셨습니다!"

        incomplete_names = []
        for r in routines_list:
            try:
                ci = await checkin_repo.get_checkin(r['id'], ld_date)
                # If no record or not checked and not skipped -> incomplete
                if not ci or (not ci.get('checked_at') and not ci.get('skipped')):
                    incomplete_names.append(r.get('name') or f"루틴{r.get('id')}")
            except Exception as e:
                print("_compose_reminder_message: checkin lookup error:", e)
                # On error, assume incomplete to be safe
                incomplete_names.append(r.get('name') or f"루틴{r.get('id')}")
        if not incomplete_names:
            return f"{date_str}{particle} 모든 루틴을 달성하셨어요! 잘하셨습니다!"

        # Build Korean list with commas
        joined = ", ".join(incomplete_names)
        return f"{date_str}{particle} {joined}를 미달성하셨어요! 혹시 체크를 잊으셨다면 지금 해보시는게 어떨까요?"
