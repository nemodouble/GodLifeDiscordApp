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

    @discord.ui.button(label="루틴 관리", custom_id="ui:manage_routines")
    async def btn_add_routine(self, itx: discord.Interaction, btn: discord.ui.Button):
        print("MainPanelView: 루틴 관리 버튼 클릭 by", itx.user)
        await itx.response.defer(ephemeral=True)
        cog = itx.client.get_cog("UICog")
        if cog:
            try:
                await cog.open_routine_manager(itx)
            except Exception as e:
                print("open_routine_manager 에러:", e)
                await itx.followup.send("루틴 관리 열기 중 오류가 발생했습니다.", ephemeral=True)
        else:
            await itx.followup.send("UICog를 찾을 수 없습니다.", ephemeral=True)

    @discord.ui.button(label="목표 관리", custom_id="ui:manage_goals")
    async def btn_add_goal(self, itx: discord.Interaction, btn: discord.ui.Button):
        print("MainPanelView: 목표 관리 버튼 클릭 by", itx.user)
        await itx.response.defer(ephemeral=True)
        cog = itx.client.get_cog("UICog")
        if cog:
            try:
                await cog.open_goal_manager(itx)
            except Exception as e:
                print("open_goal_manager 에러:", e)
                await itx.followup.send("목표 관리 열기 중 오류가 발생했습니다.", ephemeral=True)
        else:
            await itx.followup.send("UICog를 찾을 수 없습니다.", ephemeral=True)

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
    def __init__(self, routine_id: int, yyyymmdd: str, label: str = None, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        self.rid = routine_id
        self.day = yyyymmdd
        # primary toggle button: 상태 순환 (미달성 -> 완료 -> 스킵 -> 미달성)
        btn_label = label or "상태 변경"
        btn = discord.ui.Button(label=btn_label, style=discord.ButtonStyle.primary, custom_id=f"rt:toggle:{self.rid}:{self.day}")

        async def toggle_cb(itx: discord.Interaction):
            print(f"RoutineActionView: toggle 클릭 rid={self.rid} day={self.day} by", itx.user)
            cog = itx.client.get_cog("RoutineCog")
            if cog:
                try:
                    await cog.handle_toggle_button(itx, self.rid, self.day)
                except Exception as e:
                    print("handle_toggle_button 에러:", e)
                    await itx.response.send_message("상태 변경 중 오류가 발생했습니다.", ephemeral=True)
            else:
                await itx.response.send_message("RoutineCog를 찾을 수 없습니다.", ephemeral=True)

        btn.callback = toggle_cb
        self.add_item(btn)


class TodayCheckinView(discord.ui.View):
    def __init__(self, routines: list, yyyymmdd: str, timeout: Optional[float] = None):
        """하나의 메시지에 루틴별 토글 버튼을 모두 추가합니다.

        routines: list of dict with keys: id, name
        """
        # Force no timeout so buttons remain active until programmatic update
        super().__init__(timeout=None)
        self.day = yyyymmdd
        # Discord 버튼은 한 행에 최대 5개, 뷰 전체 최대 25개 제한이 있으므로 그 범위 내에서 추가
        for r in routines:
            label = f"{r.get('name')}"
            # custom_id: tc:<rid>:<yyyymmdd>
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, custom_id=f"tc:{r['id']}:{self.day}")

            def make_cb(rid: int):
                async def cb(itx: discord.Interaction):
                    print(f"TodayCheckinView: btn clicked rid={rid} day={self.day} by", itx.user)
                    cog = itx.client.get_cog("RoutineCog")
                    if cog:
                        try:
                            await cog.handle_toggle_button(itx, rid, self.day)
                        except Exception as e:
                            print("handle_toggle_button 에러:", e)
                            await itx.response.send_message("상태 변경 중 오류가 발생했습니다.", ephemeral=True)
                    else:
                        await itx.response.send_message("RoutineCog를 찾을 수 없습니다.", ephemeral=True)
                return cb

            btn.callback = make_cb(r['id'])
            self.add_item(btn)


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


class RoutineManagerView(discord.ui.View):
    def __init__(self, routines: list, timeout: Optional[float] = None):
        """루틴 목록을 받아 각 항목에 대해 편집/삭제 버튼을 제공하고, 하단에 '루틴 추가' 버튼을 둡니다."""
        super().__init__(timeout=timeout)
        self.routines = routines

        # 각 루틴에 대해 Edit / Delete 버튼 추가
        for r in routines:
            rid = r.get('id')
            name_label = r.get('name') or '무명 루틴'

            # 편집 버튼
            btn_edit = discord.ui.Button(label=f"✏️ {name_label}", style=discord.ButtonStyle.secondary, custom_id=f"rm:edit:{rid}")
            def make_edit_cb(rid_inner: int):
                async def cb(itx: discord.Interaction):
                    print(f"RoutineManagerView: edit 클릭 rid={rid_inner} by", itx.user)
                    await itx.response.defer(ephemeral=True)
                    cog = itx.client.get_cog('UICog')
                    if cog:
                        try:
                            await cog.open_edit_routine_modal(itx, rid_inner)
                        except Exception as e:
                            print('open_edit_routine_modal 에러:', e)
                            await itx.followup.send('루틴 편집 열기 중 오류가 발생했습니다.', ephemeral=True)
                    else:
                        await itx.followup.send('UICog를 찾을 수 없습니다.', ephemeral=True)
                return cb
            btn_edit.callback = make_edit_cb(rid)
            self.add_item(btn_edit)

            # 삭제 버튼
            btn_del = discord.ui.Button(label=f"🗑️ 삭제", style=discord.ButtonStyle.danger, custom_id=f"rm:delete:{rid}")
            def make_del_cb(rid_inner: int):
                async def cb(itx: discord.Interaction):
                    print(f"RoutineManagerView: delete 클릭 rid={rid_inner} by", itx.user)
                    await itx.response.defer(ephemeral=True)
                    cog = itx.client.get_cog('UICog')
                    if cog:
                        try:
                            await cog.process_delete_routine(itx, rid_inner)
                        except Exception as e:
                            print('process_delete_routine 에러:', e)
                            await itx.followup.send('루틴 삭제 중 오류가 발생했습니다.', ephemeral=True)
                    else:
                        await itx.followup.send('UICog를 찾을 수 없습니다.', ephemeral=True)
                return cb
            btn_del.callback = make_del_cb(rid)
            self.add_item(btn_del)

        # 하단에 새 루틴 추가 버튼
        btn_add = discord.ui.Button(label="루틴 추가", style=discord.ButtonStyle.success, custom_id="ui:add_routine")
        async def add_cb(itx: discord.Interaction):
            print('RoutineManagerView: 루틴 추가 클릭 by', itx.user)
            await itx.response.send_modal(AddRoutineModal())
        btn_add.callback = add_cb
        self.add_item(btn_add)


class GoalManagerView(discord.ui.View):
    def __init__(self, goals: list, timeout: Optional[float] = None):
        """목표 목록을 받아 각 항목에 대해 편집/삭제 버튼을 제공하고, 하단에 '목표 추가' 버튼을 둡니다."""
        super().__init__(timeout=timeout)
        self.goals = goals

        for g in goals:
            gid = g.get('id')
            title_label = g.get('title') or '무명 목표'

            btn_edit = discord.ui.Button(label=f"✏️ {title_label}", style=discord.ButtonStyle.secondary, custom_id=f"gm:edit:{gid}")
            def make_edit_cb(gid_inner: int):
                async def cb(itx: discord.Interaction):
                    print(f"GoalManagerView: edit 클릭 gid={gid_inner} by", itx.user)
                    await itx.response.defer(ephemeral=True)
                    cog = itx.client.get_cog('UICog')
                    if cog:
                        try:
                            await cog.open_edit_goal_modal(itx, gid_inner)
                        except Exception as e:
                            print('open_edit_goal_modal 에러:', e)
                            await itx.followup.send('목표 편집 열기 중 오류가 발생했습니다.', ephemeral=True)
                    else:
                        await itx.followup.send('UICog를 찾을 수 없습니다.', ephemeral=True)
                return cb
            btn_edit.callback = make_edit_cb(gid)
            self.add_item(btn_edit)

            btn_del = discord.ui.Button(label=f"🗑️ 삭제", style=discord.ButtonStyle.danger, custom_id=f"gm:delete:{gid}")
            def make_del_cb(gid_inner: int):
                async def cb(itx: discord.Interaction):
                    print(f"GoalManagerView: delete 클릭 gid={gid_inner} by", itx.user)
                    await itx.response.defer(ephemeral=True)
                    cog = itx.client.get_cog('UICog')
                    if cog:
                        try:
                            await cog.process_delete_goal(itx, gid_inner)
                        except Exception as e:
                            print('process_delete_goal 에러:', e)
                            await itx.followup.send('목표 삭제 중 오류가 발생했습니다.', ephemeral=True)
                    else:
                        await itx.followup.send('UICog를 찾을 수 없습니다.', ephemeral=True)
                return cb
            btn_del.callback = make_del_cb(gid)
            self.add_item(btn_del)

        btn_add = discord.ui.Button(label="목표 추가", style=discord.ButtonStyle.success, custom_id="ui:add_goal")
        async def add_goal_cb(itx: discord.Interaction):
            print('GoalManagerView: 목표 추가 클릭 by', itx.user)
            await itx.response.send_modal(AddGoalModal())
        btn_add.callback = add_goal_cb
        self.add_item(btn_add)

