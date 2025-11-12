import discord
from discord import app_commands
from discord.ext import commands

from ui.views import MainPanelView, RoutineManagerView, GoalManagerView
from ui.modals import EditRoutineModal, EditGoalModal
from repos import routine_repo
from repos import goal_repo


class UICog(commands.Cog):
    """UI 관련 명령 및 모달/버튼 처리를 위한 코그"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="routine", description="루틴 패널 전송 (테스트용)")
    async def routine(self, interaction: discord.Interaction):
        print("/routine 실행 by", interaction.user)
        # 채널에 패널 전송
        # 호출자에게만 보이는 에페메랄 메시지로 변경
        await interaction.response.send_message("루틴 패널입니다. 버튼을 사용하세요.", view=MainPanelView(), ephemeral=True)

    async def open_routine_manager(self, itx: discord.Interaction):
        """사용자 루틴 목록을 조회하고 RoutineManagerView를 에페메랄로 전송합니다."""
        user_id = str(itx.user.id)
        try:
            routines = await routine_repo.list_active_routines_for_user(user_id)
        except Exception as e:
            print("list_active_routines_for_user 에러:", e)
            await itx.followup.send("루틴 목록을 불러오는 중 오류가 발생했습니다.", ephemeral=True)
            return

        view = RoutineManagerView(routines)
        try:
            await itx.followup.send("루틴 관리입니다.", view=view, ephemeral=True)
        except Exception as e:
            print("open_routine_manager 전송 실패:", e)
            await itx.followup.send("루틴 관리 열기 중 오류가 발생했습니다.", ephemeral=True)

    async def open_goal_manager(self, itx: discord.Interaction):
        user_id = str(itx.user.id)
        try:
            goals = await goal_repo.list_active_goals_for_user(user_id)
        except Exception as e:
            print("list_active_goals_for_user 에러:", e)
            await itx.followup.send("목표 목록을 불러오는 중 오류가 발생했습니다.", ephemeral=True)
            return

        view = GoalManagerView(goals)
        try:
            await itx.followup.send("목표 관리입니다.", view=view, ephemeral=True)
        except Exception as e:
            print("open_goal_manager 전송 실패:", e)
            await itx.followup.send("목표 관리 열기 중 오류가 발생했습니다.", ephemeral=True)

    async def open_edit_routine_modal(self, itx: discord.Interaction, rid: int):
        # fetch routine data and open EditRoutineModal with initial values
        try:
            r = await routine_repo.get_routine(rid)
        except Exception as e:
            print("get_routine 에러:", e)
            await itx.followup.send("루틴을 불러오는 중 오류가 발생했습니다.", ephemeral=True)
            return
        if not r:
            await itx.followup.send("해당 루틴을 찾을 수 없습니다.", ephemeral=True)
            return
        # send modal with initial data
        modal = EditRoutineModal(rid, initial=r)
        try:
            await itx.response.send_modal(modal)
        except Exception as e:
            print("open_edit_routine_modal send_modal 에러:", e)
            await itx.followup.send("루틴 편집 모달을 여는 중 오류가 발생했습니다.", ephemeral=True)

    async def process_edit_routine(self, itx: discord.Interaction, rid: int, data: dict):
        try:
            await routine_repo.update_routine(rid, name=data.get('name'), weekend_mode=data.get('weekend_mode'), deadline_time=data.get('deadline_time'), notes=data.get('notes'))
            await itx.followup.send(f"루틴 (id={rid})이(가) 수정되었습니다.", ephemeral=True)
        except Exception as e:
            print("update_routine 에러:", e)
            await itx.followup.send("루틴 수정 중 오류가 발생했습니다.", ephemeral=True)

    async def process_delete_routine(self, itx: discord.Interaction, rid: int):
        try:
            await routine_repo.delete_routine(rid)
            await itx.followup.send(f"루틴 (id={rid})이(가) 삭제되었습니다.", ephemeral=True)
        except Exception as e:
            print("delete_routine 에러:", e)
            await itx.followup.send("루틴 삭제 중 오류가 발생했습니다.", ephemeral=True)

    async def open_edit_goal_modal(self, itx: discord.Interaction, gid: int):
        try:
            g = await goal_repo.get_goal(gid)
        except Exception as e:
            print("get_goal 에러:", e)
            await itx.followup.send("목표를 불러오는 중 오류가 발생했습니다.", ephemeral=True)
            return
        if not g:
            await itx.followup.send("해당 목표를 찾을 수 없습니다.", ephemeral=True)
            return
        modal = EditGoalModal(gid, initial=g)
        try:
            await itx.response.send_modal(modal)
        except Exception as e:
            print("open_edit_goal_modal send_modal 에러:", e)
            await itx.followup.send("목표 편집 모달을 여는 중 오류가 발생했습니다.", ephemeral=True)

    async def process_edit_goal(self, itx: discord.Interaction, gid: int, data: dict):
        try:
            await goal_repo.update_goal(gid, title=data.get('title'), period=data.get('period'), target=int(data.get('target')) if data.get('target') else None, deadline=data.get('deadline'), carry_over=int(data.get('carry_over')) if data.get('carry_over') else None)
            await itx.followup.send(f"목표 (id={gid})이(가) 수정되었습니다.", ephemeral=True)
        except Exception as e:
            print("update_goal 에러:", e)
            await itx.followup.send("목표 수정 중 오류가 발생했습니다.", ephemeral=True)

    async def process_delete_goal(self, itx: discord.Interaction, gid: int):
        try:
            await goal_repo.delete_goal(gid)
            await itx.followup.send(f"목표 (id={gid})이(가) 삭제되었습니다.", ephemeral=True)
        except Exception as e:
            print("delete_goal 에러:", e)
            await itx.followup.send("목표 삭제 중 오류가 발생했습니다.", ephemeral=True)

    async def process_add_routine(self, itx: discord.Interaction, data: dict):
        print("process_add_routine 호출 by", itx.user, data)
        # DB에 루틴 생성
        try:
            rid = await routine_repo.create_routine(
                str(itx.user.id),
                data.get("name"),
                data.get("weekend_mode"),
                data.get("deadline_time"),
                data.get("notes"),
            )
            await itx.followup.send(f"루틴을 추가했습니다 (id={rid}).", ephemeral=True)
        except Exception as e:
            print("루틴 생성 중 오류:", e)
            await itx.followup.send("루틴 생성 중 오류가 발생했습니다.", ephemeral=True)

    async def process_add_goal(self, itx: discord.Interaction, data: dict):
        print("process_add_goal 호출 by", itx.user, data)
        try:
            gid = await goal_repo.create_goal(str(itx.user.id), data.get('title'), data.get('period'), int(data.get('target')) if data.get('target') else 0, data.get('deadline'), int(data.get('carry_over')) if data.get('carry_over') else 0)
            await itx.followup.send(f"목표을 추가했습니다 (id={gid}).", ephemeral=True)
        except Exception as e:
            print("목표 생성 중 오류:", e)
            await itx.followup.send("목표 생성 중 오류가 발생했습니다.", ephemeral=True)

    async def process_skip_reason(self, itx: discord.Interaction, data: dict):
        print("process_skip_reason 호출 by", itx.user, data)
        # data: {"apply_day": "YYYY-MM-DD", "reason": "..."}
        cog = itx.client.get_cog("RoutineCog")
        if cog:
            try:
                await cog.apply_skip_from_pending(itx, data.get("apply_day"), data.get("reason"))
            except Exception as e:
                print("apply_skip_from_pending 에러:", e)
                await itx.followup.send("스킵 처리 중 오류가 발생했습니다.", ephemeral=True)
        else:
            await itx.followup.send("RoutineCog를 찾을 수 없습니다.", ephemeral=True)

    async def process_settings(self, itx: discord.Interaction, data: dict):
        print("process_settings 호출 by", itx.user, data)
        # 향후 user_settings_repo 등을 통해 저장할 수 있습니다. 현재는 응답만 보냄.
        await itx.followup.send("설정이 저장되었습니다 (테스트).", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(UICog(bot))
