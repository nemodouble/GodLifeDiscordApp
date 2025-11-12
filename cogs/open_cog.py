import discord
from discord import app_commands
from discord.ext import commands

class OpenCog(commands.Cog):
    """최초 진입용 /open 슬래시 명령 구현.

    - 사용자에게 DM으로 자리표시자 메시지 전송
    - DM 전송 실패(차단/설정) 시 에페메랄 응답으로 안내
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _send_dm(self, user: discord.User, content: str) -> bool:
        try:
            await user.send(content)
            return True
        except discord.Forbidden:
            # DM 차단 또는 봇이 DM을 보낼 권한이 없음
            return False
        except Exception:
            # 기타 예외는 실패로 간주
            return False

    @app_commands.command(name="open", description="봇 최초 진입: DM으로 자리표시자 메시지를 보냅니다.")
    async def open(self, interaction: discord.Interaction):
        # 사용자에게 DM 전송 시도
        await interaction.response.defer(ephemeral=True)

        placeholder = (
            "안녕하세요! 여기는 자리표시자 DM입니다.\n"
            "봇과의 개인 메시지가 정상 수신되는지 확인하려면 이 메시지를 확인해주세요.\n"
            "다음 단계: 봇 명령어 안내를 받고 설정을 진행할 수 있습니다."
        )

        success = await self._send_dm(interaction.user, placeholder)

        if success:
            await interaction.followup.send("DM을 보냈습니다. 받은 편지함을 확인해주세요.", ephemeral=True)
        else:
            await interaction.followup.send(
                "DM을 보낼 수 없습니다. 서버 설정에서 '서버 멤버가 나에게 메시지 보냄'을 허용하거나, 개인 메시지를 차단하지 않았는지 확인해주세요.\n"
                "또는 봇을 차단했을 수 있습니다.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(OpenCog(bot))

