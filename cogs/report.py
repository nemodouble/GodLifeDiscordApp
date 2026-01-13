import discord
from discord.ext import commands

from datetime import date, datetime
from typing import Optional

from repos import routine_repo
from repos import report_season_repo
from domain.stats import aggregate_user_metrics
from domain.time_utils import now_kst, local_day


class ReportResendView(discord.ui.View):
    """에페메럴 리포트를 일반 메시지로 다시 보내는 버튼을 제공하는 뷰."""

    def __init__(self, original_embed: discord.Embed, scope: str, timeout: float | None = 300):
        super().__init__(timeout=timeout)
        # embed는 이 View 인스턴스 수명 동안만 참조하므로 그대로 보관
        self.original_embed = original_embed
        self.scope = scope

    @discord.ui.button(label="일반 채널에 공유하기", style=discord.ButtonStyle.primary, custom_id="ui:report:resend")
    async def resend_button(self, itx: discord.Interaction, button: discord.ui.Button):
        print("ReportResendView: resend_button 클릭 by", itx.user)
        # 동일 채널에 일반(비-에페메럴) 메시지로 embed 재전송
        try:
            await itx.channel.send(embed=self.original_embed)
        except Exception as e:
            print("ReportResendView: 채널 전송 에러:", e)
            # 에러는 여전히 에페메럴로 안내
            await itx.response.send_message("리포트를 다시 보내는 중 오류가 발생했습니다.", ephemeral=True)
            return

        # 버튼을 누른 에페메럴 메시지는 간단 안내만 남기도록 업데이트 (가능하면)
        try:
            # mypy/IDE 타입체커가 discord.py의 동적 속성을 못 따라가는 경우가 있어 안전 호출
            resp = itx.response
            if not resp.is_done():
                await resp.edit_message(content="리포트를 채널에 다시 보냈습니다.", view=None)
            else:
                await itx.edit_original_response(content="리포트를 채널에 다시 보냈습니다.", view=None)
        except Exception as e:
            print("ReportResendView: 에페메럴 메시지 업데이트 에러:", e)


class ReportSeasonSelect(discord.ui.Select):
    def __init__(self, cog: "ReportCog", user_id: int, seasons: list[dict]):
        self.cog = cog
        self.owner_user_id = user_id
        options = []
        for s in seasons:
            sid = int(s["id"])
            title = str(s.get("title") or "시즌")
            start_day = str(s.get("start_day") or "")
            end_day = s.get("end_day")
            desc = f"{start_day}~{end_day or '진행중'}"
            options.append(discord.SelectOption(label=title[:100], value=str(sid), description=desc[:100]))

        super().__init__(
            placeholder="리포트를 볼 시즌을 선택하세요",
            min_values=1,
            max_values=1,
            options=options[:25],
            custom_id="ui:report:season_select",
        )

    async def callback(self, itx: discord.Interaction):
        if itx.user.id != self.owner_user_id:
            await itx.response.send_message("이 메뉴는 요청한 사람만 사용할 수 있어요.", ephemeral=True)
            return
        season_id = int(self.values[0])
        await itx.response.defer(ephemeral=True)
        await self.cog.open_scope_picker(itx, season_id)


class ReportSeasonView(discord.ui.View):
    def __init__(self, cog: "ReportCog", user: discord.abc.User, seasons: list[dict], timeout: float | None = 300):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user.id
        self.add_item(ReportSeasonSelect(cog, user.id, seasons))

    async def _ensure_owner(self, itx: discord.Interaction) -> bool:
        if itx.user.id != self.user_id:
            await itx.response.send_message("이 메뉴는 요청한 사람만 사용할 수 있어요.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="➕ 새 시즌 시작(다시 마음먹기)", style=discord.ButtonStyle.success, custom_id="ui:report:season_new")
    async def season_new(self, itx: discord.Interaction, button: discord.ui.Button):
        if not await self._ensure_owner(itx):
            return
        await itx.response.defer(ephemeral=True)
        # 기본: 오늘 local_day를 시즌 시작일로(리포트는 오늘 제외라, 실질 집계는 내일부터 느낌)
        start = local_day(now_kst()).isoformat()
        title = f"시즌 {start}"
        try:
            new_id = await report_season_repo.create_new_season(str(itx.user.id), title=title, start_day=start, auto_close_prev=True)
        except Exception as e:
            print("create_new_season error:", e)
            await itx.followup.send("새 시즌을 시작하는 중 오류가 발생했어요.", ephemeral=True)
            return
        await itx.followup.send(f"새 시즌을 시작했어요: **{title}**", ephemeral=True)
        await self.cog.open_scope_picker(itx, new_id)


class ReportScopeView(discord.ui.View):
    """시즌 선택 후, 기간(7일/30일/전체)을 선택하는 뷰."""

    def __init__(self, cog: "ReportCog", user: discord.abc.User, season_id: int, timeout: float | None = 300):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.user_id = user.id
        self.season_id = season_id

    async def _ensure_owner(self, itx: discord.Interaction) -> bool:
        if itx.user.id != self.user_id:
            try:
                await itx.response.send_message("이 리포트는 다른 사용자의 요청으로 생성되었습니다.", ephemeral=True)
            except Exception:
                pass
            return False
        return True

    async def _handle_scope(self, itx: discord.Interaction, scope: str):
        if not await self._ensure_owner(itx):
            return
        if not itx.response.is_done():
            await itx.response.defer(ephemeral=True)
        await self.cog.generate_report(itx, scope, season_id=self.season_id)

    @discord.ui.button(label="최근 7일", style=discord.ButtonStyle.primary, custom_id="ui:report:scope:7d")
    async def scope_7d(self, itx: discord.Interaction, button: discord.ui.Button):
        await self._handle_scope(itx, "7d")

    @discord.ui.button(label="최근 30일", style=discord.ButtonStyle.secondary, custom_id="ui:report:scope:30d")
    async def scope_30d(self, itx: discord.Interaction, button: discord.ui.Button):
        await self._handle_scope(itx, "30d")

    @discord.ui.button(label="전체 기간", style=discord.ButtonStyle.secondary, custom_id="ui:report:scope:all")
    async def scope_all(self, itx: discord.Interaction, button: discord.ui.Button):
        await self._handle_scope(itx, "all")


class ReportCog(commands.Cog):
    """루틴 달성 리포트를 임베드로 보여주는 Cog.

    - /report 명령: 기본 7일치 통계
    - /report scope: 7d | 30d | all 선택 가능
    - UI 버튼(ReportScopeView)에서도 같은 로직 재사용
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _build_summary_embed(self, user: discord.abc.User, metrics: dict, scope: str, season: dict | None) -> discord.Embed:
        today = local_day(now_kst())

        scope_label = {
            "7d": "최근 7일",
            "30d": "최근 30일",
            "all": "전체 기간",
        }.get(scope, "최근 7일")

        summary = metrics.get("summary", {})
        by_routine = metrics.get("by_routine", [])

        season_title = None
        season_range = None
        if season:
            season_title = season.get("title") or "시즌"
            season_range = f"{season.get('start_day')}~{season.get('end_day') or '진행중'}"

        desc = f"기간: **{scope_label}** 기준 달성률 통계입니다."
        if season_title:
            desc = f"시즌: **{season_title}** ({season_range})\n" + desc

        embed = discord.Embed(
            title=f"{user.display_name} 님의 루틴 리포트",
            description=desc,
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
                value="활성화된 루틴이 없거나, 선택한 시즌/기간에 집계할 데이터가 없습니다.",
                inline=False,
            )
            return embed

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

    async def open_report_menu(self, itx: discord.Interaction):
        user_id = str(itx.user.id)
        # 시즌이 없으면 기본 시즌 생성
        try:
            await report_season_repo.ensure_default_season(user_id)
            seasons = await report_season_repo.list_seasons_for_user(user_id)
        except Exception as e:
            print("list seasons error:", e)
            await itx.response.send_message("시즌 정보를 불러오는 중 오류가 발생했어요.", ephemeral=True)
            return
        await itx.response.send_message("리포트를 볼 시즌을 선택해 주세요.", view=ReportSeasonView(self, itx.user, seasons), ephemeral=True)

    async def open_scope_picker(self, itx: discord.Interaction, season_id: int):
        # 시즌 선택 후 스코프 선택으로 전환
        await itx.followup.send("보고 싶은 리포트 기간을 선택해 주세요.", view=ReportScopeView(self, itx.user, season_id), ephemeral=True)

    async def generate_report(self, itx: discord.Interaction, scope: str = "7d", *, season_id: int):
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

        # 시즌 범위 결정
        try:
            season = await report_season_repo.get_season(user_id, int(season_id))
            if not season:
                await itx.followup.send("선택한 시즌을 찾을 수 없어요.", ephemeral=True)
                return
        except Exception as e:
            print("get season error:", e)
            await itx.followup.send("시즌 정보를 불러오는 중 오류가 발생했어요.", ephemeral=True)
            return

        try:
            season_start = datetime.fromisoformat(str(season["start_day"])).date()
        except Exception:
            season_start = date.fromisoformat(str(season["start_day"]))

        season_end = None
        if season.get("end_day"):
            try:
                season_end = datetime.fromisoformat(str(season["end_day"])).date()
            except Exception:
                season_end = date.fromisoformat(str(season["end_day"]))

        try:
            metrics = await aggregate_user_metrics(user_id, routines, scope, season_start=season_start, season_end=season_end)
        except Exception as e:
            print("aggregate_user_metrics 에러:", e)
            await itx.followup.send("통계를 계산하는 중 오류가 발생했습니다.", ephemeral=True)
            return

        embed = self._build_summary_embed(itx.user, metrics, scope, season)
        # 에페메럴 리포트 + 일반 채널 재전송용 버튼 뷰 함께 전송
        await itx.followup.send(embed=embed, view=ReportResendView(embed, scope), ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        # Cog가 정상 로드되었는지 로그로 확인용
        print("ReportCog loaded: /report 명령 및 UI 리포트 버튼 사용 가능")

    @discord.app_commands.command(name="report", description="(현재 시즌) 루틴 달성률 리포트를 보여줍니다.")
    @discord.app_commands.describe(
        scope="기간(7d/30d/all). 비우면 7d",
        season_id="특정 시즌 ID를 지정하면 그 시즌을 출력합니다(비우면 현재 시즌).",
    )
    async def report(self, itx: discord.Interaction, scope: str = "7d", season_id: Optional[int] = None):
        """기본: 현재 시즌의 최근 7일 리포트.

        - season_id를 주면 해당 시즌 출력
        - scope는 7d/30d/all
        """
        await itx.response.defer(ephemeral=True)
        user_id = str(itx.user.id)

        try:
            if season_id is None:
                current = await report_season_repo.get_or_create_current_season(user_id)
                season_id = int(current["id"]) if current.get("id") is not None else None

            if season_id is None:
                await itx.followup.send("현재 시즌을 찾을 수 없어요. 잠시 후 다시 시도해 주세요.", ephemeral=True)
                return

            await self.generate_report(itx, scope, season_id=int(season_id))
        except Exception as e:
            print("/report error:", e)
            await itx.followup.send("리포트를 생성하는 중 오류가 발생했어요.", ephemeral=True)


class SeasonCog(commands.Cog):
    """시즌(다시 마음먹기) 관련 명령을 분리한 Cog."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @discord.app_commands.command(name="season_restart", description="새 시즌을 시작합니다(다시 마음먹기).")
    async def season_restart(self, itx: discord.Interaction):
        await itx.response.defer(ephemeral=True)
        user_id = str(itx.user.id)
        start = local_day(now_kst()).isoformat()
        title = f"시즌 {start}"

        try:
            new_id = await report_season_repo.create_new_season(user_id, title=title, start_day=start, auto_close_prev=True)
        except Exception as e:
            print("season_restart create_new_season error:", e)
            await itx.followup.send("새 시즌을 시작하는 중 오류가 발생했어요.", ephemeral=True)
            return

        await itx.followup.send(f"새 시즌을 시작했어요: **{title}** (id={new_id})", ephemeral=True)

    @discord.app_commands.command(name="season_list", description="내 시즌 목록과 시즌 ID를 보여줍니다.")
    async def season_list(self, itx: discord.Interaction):
        await itx.response.defer(ephemeral=True)
        user_id = str(itx.user.id)

        try:
            await report_season_repo.ensure_default_season(user_id)
            seasons = await report_season_repo.list_seasons_for_user(user_id, limit=12)
        except Exception as e:
            print("season_list error:", e)
            await itx.followup.send("시즌 목록을 불러오는 중 오류가 발생했어요.", ephemeral=True)
            return

        if not seasons:
            await itx.followup.send("시즌이 아직 없어요. /season_restart 로 새 시즌을 시작해 보세요.", ephemeral=True)
            return

        lines = []
        for idx, s in enumerate(seasons, start=1):
            sid = s.get("id")
            title = s.get("title") or "시즌"
            start_day = s.get("start_day")
            end_day = s.get("end_day") or "진행중"
            lines.append(f"{idx}. **{title}** — id=`{sid}` · {start_day}~{end_day}")

        msg = "아래의 `season_id`를 /report에 넣으면 해당 시즌을 볼 수 있어요.\n\n" + "\n".join(lines)
        await itx.followup.send(msg[:1800], ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ReportCog(bot))
    await bot.add_cog(SeasonCog(bot))
