import discord
from discord import app_commands
from discord.ext import commands

from ui.views import MainPanelView
from repos import routine_repo


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
        await itx.followup.send("목표 추가 요청을 받았습니다 (테스트).", ephemeral=True)

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
