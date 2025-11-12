import discord
from typing import Optional

class AddRoutineModal(discord.ui.Modal, title="루틴 추가"):
    name = discord.ui.TextInput(label="이름")
    weekend_mode = discord.ui.TextInput(label="주말 모드(weekday|weekend|all)")
    deadline_time = discord.ui.TextInput(label="마감(HH:MM)", required=False)
    notes = discord.ui.TextInput(label="메모", style=discord.TextStyle.paragraph, required=False)

    async def on_submit(self, itx: discord.Interaction):
        print("AddRoutineModal submitted by", itx.user)
        print("values:", self.name.value, self.weekend_mode.value, self.deadline_time.value, self.notes.value)
        # 에페메랄 ACK
        await itx.response.defer(ephemeral=True)
        cog = itx.client.get_cog("UICog")
        if cog:
            try:
                await cog.process_add_routine(itx, {
                    "name": self.name.value,
                    "weekend_mode": self.weekend_mode.value,
                    "deadline_time": self.deadline_time.value,
                    "notes": self.notes.value,
                })
            except Exception as e:
                print("process_add_routine 호출 중 에러:", e)
        else:
            await itx.followup.send("UICog를 찾을 수 없습니다.", ephemeral=True)


class AddGoalModal(discord.ui.Modal, title="목표 추가"):
    title_field = discord.ui.TextInput(label="제목")
    period = discord.ui.TextInput(label="주기 (days)")
    target = discord.ui.TextInput(label="목표값")
    deadline = discord.ui.TextInput(label="마감(YYYY-MM-DD)", required=False)
    carry_over = discord.ui.TextInput(label="이월 허용 여부(true|false)", required=False)

    async def on_submit(self, itx: discord.Interaction):
        print("AddGoalModal submitted by", itx.user)
        print("values:", self.title_field.value, self.period.value, self.target.value, self.deadline.value, self.carry_over.value)
        await itx.response.defer(ephemeral=True)
        cog = itx.client.get_cog("UICog")
        if cog:
            try:
                await cog.process_add_goal(itx, {
                    "title": self.title_field.value,
                    "period": self.period.value,
                    "target": self.target.value,
                    "deadline": self.deadline.value,
                    "carry_over": self.carry_over.value,
                })
            except Exception as e:
                print("process_add_goal 호출 중 에러:", e)
        else:
            await itx.followup.send("UICog를 찾을 수 없습니다.", ephemeral=True)


class SkipReasonModal(discord.ui.Modal, title="스킵 사유"):
    reason = discord.ui.TextInput(label="사유", style=discord.TextStyle.paragraph)

    def __init__(self, apply_day: Optional[str] = None):
        super().__init__()
        self.apply_day = apply_day

    async def on_submit(self, itx: discord.Interaction):
        print("SkipReasonModal submitted by", itx.user, "apply_day=", self.apply_day)
        print("reason:", self.reason.value)
        await itx.response.defer(ephemeral=True)
        cog = itx.client.get_cog("UICog")
        if cog:
            try:
                await cog.process_skip_reason(itx, {"apply_day": self.apply_day, "reason": self.reason.value})
            except Exception as e:
                print("process_skip_reason 호출 중 에러:", e)
        else:
            await itx.followup.send("UICog를 찾을 수 없습니다.", ephemeral=True)


class SettingsModal(discord.ui.Modal, title="설정"):
    reminder_time = discord.ui.TextInput(label="리마인더 시간(HH:MM)", required=False)

    async def on_submit(self, itx: discord.Interaction):
        print("SettingsModal submitted by", itx.user)
        print("reminder_time:", self.reminder_time.value)
        await itx.response.defer(ephemeral=True)
        cog = itx.client.get_cog("UICog")
        if cog:
            try:
                await cog.process_settings(itx, {"reminder_time": self.reminder_time.value})
            except Exception as e:
                print("process_settings 호출 중 에러:", e)
        else:
            await itx.followup.send("UICog를 찾을 수 없습니다.", ephemeral=True)


# --- Edit modals for Routine and Goal ---
class EditRoutineModal(discord.ui.Modal, title="루틴 편집"):
    name = discord.ui.TextInput(label="이름")
    weekend_mode = discord.ui.TextInput(label="주말 모드(weekday|weekend|all)")
    deadline_time = discord.ui.TextInput(label="마감(HH:MM)", required=False)
    notes = discord.ui.TextInput(label="메모", style=discord.TextStyle.paragraph, required=False)

    def __init__(self, routine_id: int, initial: Optional[dict] = None):
        super().__init__()
        self.rid = routine_id
        # 초기값이 주어지면 각 TextInput의 default 값을 설정
        if initial:
            try:
                self.name.default = initial.get('name', '')
                self.weekend_mode.default = initial.get('weekend_mode', '')
                self.deadline_time.default = initial.get('deadline_time', '')
                self.notes.default = initial.get('notes', '')
            except Exception:
                pass

    async def on_submit(self, itx: discord.Interaction):
        print("EditRoutineModal submitted by", itx.user, "rid=", self.rid)
        await itx.response.defer(ephemeral=True)
        cog = itx.client.get_cog("UICog")
        if cog:
            try:
                await cog.process_edit_routine(itx, self.rid, {
                    "name": self.name.value,
                    "weekend_mode": self.weekend_mode.value,
                    "deadline_time": self.deadline_time.value,
                    "notes": self.notes.value,
                })
            except Exception as e:
                print("process_edit_routine 호출 중 에러:", e)
        else:
            await itx.followup.send("UICog를 찾을 수 없습니다.", ephemeral=True)


class EditGoalModal(discord.ui.Modal, title="목표 편집"):
    title_field = discord.ui.TextInput(label="제목")
    period = discord.ui.TextInput(label="주기 (days)")
    target = discord.ui.TextInput(label="목표값")
    deadline = discord.ui.TextInput(label="마감(YYYY-MM-DD)", required=False)
    carry_over = discord.ui.TextInput(label="이월 허용 여부(true|false)", required=False)

    def __init__(self, goal_id: int, initial: Optional[dict] = None):
        super().__init__()
        self.gid = goal_id
        if initial:
            try:
                self.title_field.default = initial.get('title', '')
                self.period.default = initial.get('period', '')
                self.target.default = str(initial.get('target', ''))
                self.deadline.default = initial.get('deadline', '')
                self.carry_over.default = str(initial.get('carry_over', ''))
            except Exception:
                pass

    async def on_submit(self, itx: discord.Interaction):
        print("EditGoalModal submitted by", itx.user, "gid=", self.gid)
        await itx.response.defer(ephemeral=True)
        cog = itx.client.get_cog("UICog")
        if cog:
            try:
                await cog.process_edit_goal(itx, self.gid, {
                    "title": self.title_field.value,
                    "period": self.period.value,
                    "target": self.target.value,
                    "deadline": self.deadline.value,
                    "carry_over": self.carry_over.value,
                })
            except Exception as e:
                print("process_edit_goal 호출 중 에러:", e)
        else:
            await itx.followup.send("UICog를 찾을 수 없습니다.", ephemeral=True)

