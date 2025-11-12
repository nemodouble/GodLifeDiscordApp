import discord
from discord.ext import commands
from typing import Dict, Tuple, Any

from repos import routine_repo, checkin_repo
from domain.time_utils import now_kst, local_day, is_valid_day
from ui.views import RoutineActionView


class RoutineCog(commands.Cog):
    """루틴 관련 체크인 UI 및 버튼 처리 코그

    - open_today_checkin_list: is_valid_day 필터를 적용해 유효 루틴만 표시
    - handle_button: done/undo 처리 후 메시지 갱신
    - record_pending_skip / apply_skip_from_pending: 스킵 사유 모달 흐름 지원
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # key: (user_id, yyyymmdd) -> info dict
        self.pending_skips: Dict[Tuple[str, str], Dict[str, Any]] = {}

    async def record_pending_skip(self, channel_id: int, message_id: int, rid: int, yyyymmdd: str, user_id: int):
        key = (str(user_id), str(yyyymmdd))
        self.pending_skips[key] = {
            "channel_id": int(channel_id),
            "message_id": int(message_id),
            "rid": int(rid),
            "user_id": str(user_id),
        }

    async def apply_skip_from_pending(self, itx: discord.Interaction, apply_day: str, reason: str):
        user_id = str(itx.user.id)
        key = (user_id, str(apply_day))
        info = self.pending_skips.get(key)
        if not info:
            await itx.followup.send("대기중인 스킵 요청을 찾을 수 없습니다.", ephemeral=True)
            return

        try:
            await checkin_repo.skip_checkin(info["rid"], user_id, apply_day, reason)
        except Exception as e:
            print("skip_checkin 에러:", e)
            await itx.followup.send("스킵 처리 중 오류가 발생했습니다.", ephemeral=True)
            return

        # 원본(에페메랄 등) 메시지를 편집하려 시도하면 권한/접근성 문제로 실패할 수 있으므로
        # 여기서는 원본 메시지 편집 대신 모달 제출자에게 followup으로 처리 결과를 알립니다.
        try:
            del self.pending_skips[key]
        except KeyError:
            pass

        await itx.followup.send(f"스킵이 정상적으로 처리되었습니다. (루틴 #{info['rid']})", ephemeral=True)

    async def open_today_checkin_list(self, itx: discord.Interaction):
        # 현재 KST 기준 local_day를 사용
        user_id = str(itx.user.id)
        now = now_kst()
        ld = local_day(now)

        # 준비된(활성 & 주말모드 필터 통과) 루틴 목록
        try:
            routines = await routine_repo.prepare_checkin_for_date(user_id, now)
        except Exception as e:
            print("prepare_checkin_for_date 에러:", e)
            await itx.followup.send("루틴 목록을 불러오는 중 오류가 발생했습니다.", ephemeral=True)
            return

        sent = 0
        for r in routines:
            try:
                if await is_valid_day(user_id, r.get("weekend_mode", "weekday"), ld):
                    content = f"[{r['id']}] {r['name']}"
                    view = RoutineActionView(r['id'], ld.isoformat())
                    await itx.followup.send(content, view=view, ephemeral=True)
                    sent += 1
            except Exception as e:
                print("is_valid_day 체크 중 오류:", e)
                # 건너뜀
                continue

        if sent == 0:
            await itx.followup.send("오늘 체크인 대상 루틴이 없습니다.", ephemeral=True)

    async def handle_button(self, itx: discord.Interaction, action: str, rid: int, yyyymmdd: str):
        # 버튼 콜백에서 호출됨. 이미 interaction이 있으므로 응답 후 DB 갱신 및 메시지 편집
        await itx.response.defer(ephemeral=True)
        user_id = str(itx.user.id)
        try:
            if action == "done":
                await checkin_repo.upsert_checkin_done(rid, user_id, yyyymmdd)
            elif action == "undo":
                await checkin_repo.undo_checkin(rid, yyyymmdd)
            else:
                await itx.followup.send("알 수 없는 액션입니다.", ephemeral=True)
                return
        except Exception as e:
            print("handle_button DB 에러:", e)
            await itx.followup.send("DB 처리 중 오류가 발생했습니다.", ephemeral=True)
            return

        # DB 조회로 상태 결정
        try:
            ci = await checkin_repo.get_checkin(rid, yyyymmdd)
            if ci:
                if ci.get("skipped"):
                    status = f"스킵 (사유: {ci.get('skip_reason')})"
                elif ci.get("checked_at"):
                    status = "완료"
                elif ci.get("undone_at"):
                    status = "되돌림"
                else:
                    status = "미완료"
            else:
                status = "미완료"
        except Exception as e:
            print("get_checkin 에러:", e)
            status = "상태 알 수 없음"

        # 원본 메시지(특히 에페메랄)는 봇이 편집할 수 없는 경우가 많아 편집 대신 followup으로 상태를 알립니다.
        await itx.followup.send(f"처리 완료: {status}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RoutineCog(bot))
