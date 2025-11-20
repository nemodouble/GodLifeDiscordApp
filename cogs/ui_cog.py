import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from ui.views import MainPanelView, RoutineManagerView, GoalManagerView
from ui.modals import EditRoutineModal, EditGoalModal, SettingsModal
from repos import routine_repo
from repos import goal_repo
from repos import user_settings_repo


class UICog(commands.Cog):
    """UI 관련 명령 및 모달/버튼 처리를 위한 코그"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="checkin", description="오늘 일일 체크인 패널을 엽니다.")
    async def checkin(self, interaction: discord.Interaction):
        """일일 체크인 패널(오늘 루틴 진행 상태 + 토글 버튼)을 여는 명령"""
        print("/checkin 실행 by", interaction.user)
        cog = interaction.client.get_cog("RoutineCog")
        if cog:
            try:
                await cog.open_today_checkin_list(interaction)
            except Exception as e:
                print("open_today_checkin_list 에러:", e)
                try:
                    if not interaction.response.is_done():
                        await interaction.response.send_message("오늘 체크인 열기 중 오류가 발생했습니다.", ephemeral=True)
                    else:
                        await interaction.followup.send("오늘 체크인 열기 중 오류가 발생했습니다.", ephemeral=True)
                except Exception:
                    pass
        else:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("RoutineCog를 찾을 수 없습니다.", ephemeral=True)
                else:
                    await interaction.followup.send("RoutineCog를 찾을 수 없습니다.", ephemeral=True)
            except Exception:
                pass

    @app_commands.command(name="routine", description="루틴 관리 패널을 엽니다.")
    async def routine(self, interaction: discord.Interaction):
        """루틴 관리 패널을 여는 명령"""
        print("/routine 실행 by", interaction.user)
        await interaction.response.defer(ephemeral=True)
        await self.open_routine_manager(interaction)

    @app_commands.command(name="goal", description="목표 관리 패널을 엽니다.")
    async def goal(self, interaction: discord.Interaction):
        """목표 관리 패널을 여는 명령"""
        print("/goal 실행 by", interaction.user)
        await interaction.response.defer(ephemeral=True)
        await self.open_goal_manager(interaction)

    @app_commands.command(name="setting", description="개인 설정을 관리합니다.")
    async def setting(self, interaction: discord.Interaction):
        """설정(리마인더 시간 등) 관리 패널을 여는 명령"""
        print("/setting 실행 by", interaction.user)
        # 현재는 리마인더 시간 하나만 설정
        await interaction.response.send_modal(SettingsModal())

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
        # If the interaction has already been responded to, we cannot call send_modal.
        try:
            if itx.response.is_done():
                await itx.followup.send("이 상호작용은 이미 응답되었습니다. 버튼을 다시 눌러주세요.", ephemeral=True)
                return
        except Exception:
            # If inspection fails for any reason, continue and let send_modal raise if invalid.
            pass

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
            fields = {
                'name': data.get('name'),
                'weekend_mode': data.get('weekend_mode'),
                'deadline_time': data.get('deadline_time'),
                'notes': data.get('notes'),
            }
            # order_index 가 전달되었다면 정수로 파싱하여 포함
            raw_order = (data.get('order_index') or '').strip()
            if raw_order:
                try:
                    fields['order_index'] = int(raw_order)
                except ValueError:
                    # 잘못된 값이면 무시하고 기존 값 유지
                    pass
            await routine_repo.update_routine(rid, **fields)
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
            if itx.response.is_done():
                await itx.followup.send("이 상호작용은 이미 응답되었습니다. 버튼을 다시 눌러주세요.", ephemeral=True)
                return
        except Exception:
            pass

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
            await goal_repo.update_goal(gid, title=data.get('title'), deadline=data.get('deadline'), description=data.get('description'))
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
            raw_order = (data.get('order_index') or '').strip()
            order_index = None
            if raw_order:
                try:
                    order_index = int(raw_order)
                except ValueError:
                    order_index = None

            rid = await routine_repo.create_routine(
                str(itx.user.id),
                data.get("name"),
                data.get("weekend_mode"),
                data.get("deadline_time"),
                data.get("notes"),
                order_index=order_index,
            )
            await itx.followup.send(f"루틴을 추가했습니다 (id={rid}).", ephemeral=True)
        except Exception as e:
            print("루틴 생성 중 오류:", e)
            await itx.followup.send("루틴 생성 중 오류가 발생했습니다.", ephemeral=True)

    async def process_add_goal(self, itx: discord.Interaction, data: dict):
        print("process_add_goal 호출 by", itx.user, data)
        try:
            gid = await goal_repo.create_goal(str(itx.user.id), data.get('title'), data.get('deadline'), data.get('description'))
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
        # 저장: user_settings에 reminder_time을 upsert
        try:
            reminder_time = data.get('reminder_time') or "23:00"
            await user_settings_repo.upsert_user_settings(str(itx.user.id), reminder_time=reminder_time)
        except Exception as e:
            print("user_settings upsert 에러:", e)
            await itx.followup.send("설정 저장 중 오류가 발생했습니다.", ephemeral=True)
            return

        # 스케줄러가 즉시 반영하도록 트리거
        try:
            scheduler = itx.client.get_cog('SchedulerCog')
            if scheduler and hasattr(scheduler, '_run_correction_once'):
                # 비동기로 즉시 검사 실행
                asyncio.create_task(scheduler._run_correction_once())
        except Exception as e:
            print("scheduler trigger 에러:", e)

        await itx.followup.send("설정이 저장되었습니다.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(UICog(bot))
