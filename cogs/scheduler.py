# New scheduler cog implementing daily prompts and deadline reminders (MVP)
# ...existing code...
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
            now = now_kst()
            # 스케줄링 대상 사용자 목록 조회
            conn = await connect_db()
            try:
                cur = await conn.execute("SELECT user_id, tz, reminder_time FROM user_settings")
                users = await cur.fetchall()
                await cur.close()
            finally:
                await conn.close()

            for u in users:
                user_id = str(u[0])
                tz_name = u[1] or "Asia/Seoul"
                reminder_time = u[2] or "08:00"
                # daily prompt
                when_dt = self._make_when_dt_for_date(now, tz_name, reminder_time)
                if when_dt > now:
                    asyncio.create_task(self._daily_prompt_task(user_id, when_dt))
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
                    valid.append(r)
            except Exception as e:
                print("daily_prompt: is_valid_day error:", e)
                continue
        if len(valid) == 0:
            # 보낼 필요 없음
            self.sent_keys.add(key)
            return
        # DM 전송
        content = f"오늘의 루틴 안내 ({ld.isoformat()})\n" + "\n".join([f"[{r['id']}] {r['name']}" for r in valid])
        await self._safe_send_dm(user_id, content)
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
        # 미완료: DM 보내기
        content = f"루틴 미완료 알림: [{routine_id}] {routine.get('name')}\n날짜: {ld.isoformat()}"
        await self._safe_send_dm(user_id, content)
        self.sent_keys.add(key)

    async def _safe_send_dm(self, user_id: str, content: str) -> None:
        try:
            user = await self.bot.fetch_user(int(user_id))
            await user.send(content)
        except Exception as e:
            print("_safe_send_dm error:", e)

    async def _correction_loop(self) -> None:
        """5분마다 지나간 트리거를 확인해 즉시 처리한다."""
        try:
            while True:
                try:
                    await self._run_correction_once()
                except Exception as e:
                    print("correction loop error:", e)
                await asyncio.sleep(300)  # 5분
        except asyncio.CancelledError:
            return

    async def _run_correction_once(self) -> None:
        now = now_kst()
        window_start = now - timedelta(minutes=5)
        # 스캔: 모든 사용자, 각 사용자에 대해 daily + routines의 deadline 계산
        conn = await connect_db()
        try:
            cur = await conn.execute("SELECT user_id, tz, reminder_time FROM user_settings")
            users = await cur.fetchall()
            await cur.close()
        finally:
            await conn.close()

        for u in users:
            user_id = str(u[0])
            tz_name = u[1] or "Asia/Seoul"
            reminder_time = u[2] or "08:00"
            # daily
            when_daily = self._make_when_dt_for_date(now, tz_name, reminder_time)
            if window_start <= when_daily <= now:
                # 실행
                ld = local_day(now)
                key = (user_id, ld.isoformat(), "daily_prompt", None)
                if key not in self.sent_keys:
                    await self._daily_prompt_task(user_id, when_daily)
            # routines
            try:
                routines = await routine_repo.list_active_routines_for_user(user_id)
            except Exception as e:
                print("correction: routine list error:", e)
                routines = []
            for r in routines:
                dt_str = r.get("deadline_time") or reminder_time
                when_r = self._make_when_dt_for_date(now, tz_name, dt_str)
                if window_start <= when_r <= now:
                    ld = local_day(now)
                    key = (user_id, ld.isoformat(), "deadline_reminder", r["id"])
                    if key not in self.sent_keys:
                        await self._deadline_task(user_id, r["id"], when_r)


async def setup(bot: commands.Bot):
    await bot.add_cog(SchedulerCog(bot))

