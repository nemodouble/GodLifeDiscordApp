import discord
from discord.ext import commands

from repos import routine_repo
from domain.stats import aggregate_user_metrics
from domain.time_utils import now_kst, local_day


class ReportCog(commands.Cog):
    """루틴 달성 리포트를 임베드로 보여주는 Cog.

    - /report 명령: 기본 7일치 통계
    - /report scope: 7d | 30d | all 선택 가능
    - UI 버튼(ReportScopeView)에서도 같은 로직 재사용
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _build_summary_embed(self, user: discord.abc.User, metrics: dict, scope: str) -> discord.Embed:
        today = local_day(now_kst())

        scope_label = {
            "7d": "최근 7일",
            "30d": "최근 30일",
            "all": "전체 기간",
        }.get(scope, "최근 7일")

        summary = metrics.get("summary", {})
        by_routine = metrics.get("by_routine", [])

        embed = discord.Embed(
            title=f"{user.display_name} 님의 루틴 리포트",
            description=f"기간: **{scope_label}** 기준 달성률 통계입니다.",
            color=discord.Color.green(),
        )
        embed.set_footer(text=today.strftime("%Y-%m-%d 기준"))

        avg_rate = summary.get("avg_rate", 0.0) * 100
        total_done = summary.get("total_done", 0)
        total_valid = summary.get("total_valid", 0)
        embed.add_field(
            name="전체 요약",
            value=(
                f"평균 달성률: **{avg_rate:.1f}%**\n"
                f"완료 횟수: **{total_done}회** / 유효 일수: **{total_valid}일**"
            ),
            inline=False,
        )

        if not by_routine:
            embed.add_field(
                name="루틴 없음",
                value="활성화된 루틴이 없습니다. 먼저 루틴을 등록해 주세요.",
                inline=False,
            )
            return embed

        # 루틴별 상세
        lines = []
        # 달성률 높은 순으로 정렬
        sorted_routines = sorted(by_routine, key=lambda r: r.get("rate", 0.0), reverse=True)
        for r in sorted_routines:
            rate = r.get("rate", 0.0) * 100
            done = r.get("done", 0)
            valid = r.get("valid", 0)
            max_streak = r.get("max_streak", 0)
            current_streak = r.get("current_streak", 0)
            name = r.get("name", "(이름 없음)")

            line = (
                f"**{name}** — {rate:.1f}% ({done}/{valid})\n"
                f"  · 최대 연속: {max_streak}일, 현재 연속: {current_streak}일"
            )
            lines.append(line)

        embed.add_field(
            name="루틴별 상세",
            value="\n".join(lines)[:1000] or "데이터가 없습니다.",
            inline=False,
        )
        return embed

    async def generate_report(self, itx: discord.Interaction, scope: str = "7d"):
        """UI 버튼/슬래시 명령 양쪽에서 공통으로 사용하는 리포트 생성 로직."""
        scope = (scope or "7d").lower()
        if scope not in ("7d", "30d", "all"):
            scope = "7d"

        user_id = str(itx.user.id)

        try:
            routines = await routine_repo.list_active_routines_for_user(user_id)
        except Exception as e:
            print("list_active_routines_for_user 에러:", e)
            await itx.followup.send("루틴 정보를 불러오는 중 오류가 발생했습니다.", ephemeral=True)
            return

        if not routines:
            await itx.followup.send("활성화된 루틴이 없습니다. 먼저 루틴을 등록해 주세요.", ephemeral=True)
            return

        try:
            metrics = await aggregate_user_metrics(user_id, routines, scope)
        except Exception as e:
            print("aggregate_user_metrics 에러:", e)
            await itx.followup.send("통계를 계산하는 중 오류가 발생했습니다.", ephemeral=True)
            return

        embed = self._build_summary_embed(itx.user, metrics, scope)
        await itx.followup.send(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        # Cog가 정상 로드되었는지 로그로 확인용
        print("ReportCog loaded: /report 명령 및 UI 리포트 버튼 사용 가능")

    @discord.app_commands.command(name="report", description="루틴 달성률 리포트를 보여줍니다.")
    @discord.app_commands.describe(scope="통계를 볼 기간: 7d(기본), 30d, all")
    async def report(self, itx: discord.Interaction, scope: str = "7d"):
        # slash 명령은 여기서 defer 한 뒤 공통 로직 호출
        await itx.response.defer(ephemeral=True)
        await self.generate_report(itx, scope)


async def setup(bot: commands.Bot):
    await bot.add_cog(ReportCog(bot))
