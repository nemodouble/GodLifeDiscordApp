import discord
from typing import Optional
from .modals import AddRoutineModal, AddGoalModal, SkipReasonModal, SettingsModal

class MainPanelView(discord.ui.View):
    def __init__(self, timeout: Optional[float] = None):
        # 영속 뷰로 동작하도록 persistent=True
        super().__init__(timeout=timeout)
        self.children  # 존재를 보장

    @discord.ui.button(label="오늘 체크인", custom_id="ui:checkin")
    async def btn_checkin(self, itx: discord.Interaction, btn: discord.ui.Button):
        print("MainPanelView: 오늘 체크인 버튼 클릭 by", itx.user)
        # 위임: RoutineCog가 실제 체크인 목록 생성 및 전송을 담당
        await itx.response.defer(ephemeral=True)
        cog = itx.client.get_cog("RoutineCog")
        if cog:
            try:
                await cog.open_today_checkin_list(itx)
            except Exception as e:
                print("open_today_checkin_list 에러:", e)
                await itx.followup.send("오늘 체크인 열기 중 오류가 발생했습니다.", ephemeral=True)
        else:
            await itx.followup.send("RoutineCog를 찾을 수 없습니다.", ephemeral=True)

    @discord.ui.button(label="루틴 추가", custom_id="ui:add_routine")
    async def btn_add_routine(self, itx: discord.Interaction, btn: discord.ui.Button):
        print("MainPanelView: 루틴 추가 버튼 클릭 by", itx.user)
        await itx.response.send_modal(AddRoutineModal())

    @discord.ui.button(label="목표 추가", custom_id="ui:add_goal")
    async def btn_add_goal(self, itx: discord.Interaction, btn: discord.ui.Button):
        print("MainPanelView: 목표 추가 버튼 클릭 by", itx.user)
        await itx.response.send_modal(AddGoalModal())

    @discord.ui.button(label="리포트", custom_id="ui:report:menu")
    async def btn_report(self, itx: discord.Interaction, btn: discord.ui.Button):
        print("MainPanelView: 리포트 버튼 클릭 by", itx.user)
        # 간단히 리포트 범위 선택 뷰를 띄움
        await itx.response.send_message("리포트 범위를 선택하세요.", view=ReportScopeView(), ephemeral=True)

    @discord.ui.button(label="설정", custom_id="ui:settings")
    async def btn_settings(self, itx: discord.Interaction, btn: discord.ui.Button):
        print("MainPanelView: 설정 버튼 클릭 by", itx.user)
        await itx.response.send_modal(SettingsModal())


class RoutineActionView(discord.ui.View):
    def __init__(self, routine_id: int, yyyymmdd: str, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        self.rid = routine_id
        self.day = yyyymmdd

        # 동적 버튼 생성 (custom_id 규칙: rt:done|undo|skip:<rid>:<yyyymmdd>)
        btn_done = discord.ui.Button(label="✅ 완료", style=discord.ButtonStyle.success, custom_id=f"rt:done:{self.rid}:{self.day}")
        btn_undo = discord.ui.Button(label="↩ 되돌리기", style=discord.ButtonStyle.secondary, custom_id=f"rt:undo:{self.rid}:{self.day}")
        btn_skip = discord.ui.Button(label="🛌 스킵", style=discord.ButtonStyle.danger, custom_id=f"rt:skip:{self.rid}:{self.day}")

        async def done_cb(itx: discord.Interaction):
            print(f"RoutineActionView: done 클릭 rid={self.rid} day={self.day} by", itx.user)
            cog = itx.client.get_cog("RoutineCog")
            if cog:
                try:
                    await cog.handle_button(itx, "done", self.rid, self.day)
                except Exception as e:
                    print("handle_button(done) 에러:", e)
                    await itx.response.send_message("완료 처리 중 오류가 발생했습니다.", ephemeral=True)
            else:
                await itx.response.send_message("RoutineCog를 찾을 수 없습니다.", ephemeral=True)

        async def undo_cb(itx: discord.Interaction):
            print(f"RoutineActionView: undo 클릭 rid={self.rid} day={self.day} by", itx.user)
            cog = itx.client.get_cog("RoutineCog")
            if cog:
                try:
                    await cog.handle_button(itx, "undo", self.rid, self.day)
                except Exception as e:
                    print("handle_button(undo) 에러:", e)
                    await itx.response.send_message("되돌리기 처리 중 오류가 발생했습니다.", ephemeral=True)
            else:
                await itx.response.send_message("RoutineCog를 찾을 수 없습니다.", ephemeral=True)

        async def skip_cb(itx: discord.Interaction):
            print(f"RoutineActionView: skip 클릭 rid={self.rid} day={self.day} by", itx.user)
            # RoutineCog가 모달 제출 후 원본 메시지를 갱신할 수 있도록 컨텍스트를 기록
            cog = itx.client.get_cog("RoutineCog")
            if cog:
                try:
                    # message/channel 정보를 기록
                    if itx.message is not None and itx.channel is not None:
                        await cog.record_pending_skip(itx.channel.id, itx.message.id, self.rid, self.day, itx.user.id)
                except Exception as e:
                    print("record_pending_skip 에러:", e)
            # 스킵 사유 모달을 띄움(모달에 루틴/일자 정보를 전달)
            await itx.response.send_modal(SkipReasonModal(self.day))

        btn_done.callback = done_cb
        btn_undo.callback = undo_cb
        btn_skip.callback = skip_cb

        self.add_item(btn_done)
        self.add_item(btn_undo)
        self.add_item(btn_skip)


class ReportScopeView(discord.ui.View):
    def __init__(self, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)

    @discord.ui.button(label="전체", custom_id="ui:report:all")
    async def btn_all(self, itx: discord.Interaction, btn: discord.ui.Button):
        print("ReportScopeView: 전체 선택 by", itx.user)
        await itx.response.defer(ephemeral=True)
        cog = itx.client.get_cog("ReportCog")
        if cog:
            try:
                await cog.generate_report(itx, "all")
            except Exception as e:
                print("ReportCog.generate_report 에러:", e)
                await itx.followup.send("리포트 생성 중 오류가 발생했습니다.", ephemeral=True)
        else:
            await itx.followup.send("ReportCog를 찾을 수 없습니다.", ephemeral=True)

    @discord.ui.button(label="30일", custom_id="ui:report:30")
    async def btn_30(self, itx: discord.Interaction, btn: discord.ui.Button):
        print("ReportScopeView: 30일 선택 by", itx.user)
        await itx.response.defer(ephemeral=True)
        cog = itx.client.get_cog("ReportCog")
        if cog:
            try:
                await cog.generate_report(itx, "30d")
            except Exception as e:
                print("ReportCog.generate_report 에러:", e)
                await itx.followup.send("리포트 생성 중 오류가 발생했습니다.", ephemeral=True)
        else:
            await itx.followup.send("ReportCog를 찾을 수 없습니다.", ephemeral=True)

    @discord.ui.button(label="7일", custom_id="ui:report:7")
    async def btn_7(self, itx: discord.Interaction, btn: discord.ui.Button):
        print("ReportScopeView: 7일 선택 by", itx.user)
        await itx.response.defer(ephemeral=True)
        cog = itx.client.get_cog("ReportCog")
        if cog:
            try:
                await cog.generate_report(itx, "7d")
            except Exception as e:
                print("ReportCog.generate_report 에러:", e)
                await itx.followup.send("리포트 생성 중 오류가 발생했습니다.", ephemeral=True)
        else:
            await itx.followup.send("ReportCog를 찾을 수 없습니다.", ephemeral=True)


class GoalListView(discord.ui.View):
    def __init__(self, goal_id: int, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        self.gid = goal_id

        btn_inc = discord.ui.Button(label="+1 진행", style=discord.ButtonStyle.primary, custom_id=f"goal:inc:{self.gid}")

        async def inc_cb(itx: discord.Interaction):
            print(f"GoalListView: +1 클릭 gid={self.gid} by", itx.user)
            await itx.response.send_message("목표 진행 +1 처리됨.", ephemeral=True)

        btn_inc.callback = inc_cb
        self.add_item(btn_inc)
