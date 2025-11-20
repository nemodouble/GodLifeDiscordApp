import discord
from discord.ext import commands
from typing import Dict, Tuple, Any
from datetime import date

from repos import routine_repo, checkin_repo
from domain.time_utils import now_kst, local_day, is_valid_day
from ui.views import TodayCheckinView


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
        # key: (user_id, yyyymmdd) -> (channel_id, message_id) for last sent checkin message (DM preferred)
        self.last_checkin_message: Dict[Tuple[str, str], Dict[str, int]] = {}

    # 날짜를 "YY-MM-DD" 형태로 포맷해서 반환합니다. (메시지에 표시할 용도)
    def _format_display_date(self, ld) -> str:
        try:
            # ld가 date 객체면 strftime, 아니면 iso string로 시도
            if hasattr(ld, 'strftime'):
                return ld.strftime("%y-%m-%d")
            # ld가 문자열(ISO)인 경우
            try:
                d = date.fromisoformat(str(ld))
                return d.strftime("%y-%m-%d")
            except Exception:
                return str(ld)
        except Exception:
            return str(ld)

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
        """오늘 일일 루틴 진행 상태 패널을 전송한다.

        - 첫 응답은 interaction.response.send_message 를 사용해 채널 메시지로 보냄
        - 실패 시 followup.send 또는 DM 으로 폴백
        """
        user_id = str(itx.user.id)
        now = now_kst()
        ld = local_day(now)

        try:
            routines = await routine_repo.prepare_checkin_for_date(user_id, now)
        except Exception as e:
            print("prepare_checkin_for_date 에러:", e)
            # 아직 응답 전이면 response, 아니면 followup 사용
            try:
                if not itx.response.is_done():
                    await itx.response.send_message("루틴 목록을 불러오는 중 오류가 발생했습니다.", ephemeral=True)
                else:
                    await itx.followup.send("루틴 목록을 불러오는 중 오류가 발생했습니다.", ephemeral=True)
            except Exception:
                pass
            return

        display = []
        for r in routines:
            try:
                if await is_valid_day(user_id, r.get("weekend_mode", "weekday"), ld):
                    try:
                        ci = await checkin_repo.get_checkin(r["id"], ld.isoformat())
                    except Exception:
                        ci = None
                    if ci and ci.get("skipped"):
                        emoji = "➡️"
                    elif ci and ci.get("checked_at"):
                        emoji = "✅"
                    else:
                        emoji = "❌"
                    display.append({"id": r["id"], "name": f"{emoji} {r['name']}"})
            except Exception as e:
                print("is_valid_day 체크 중 오류:", e)
                continue

        if not display:
            try:
                if not itx.response.is_done():
                    await itx.response.send_message("오늘 체크인 대상 루틴이 없습니다.", ephemeral=True)
                else:
                    await itx.followup.send("오늘 체크인 대상 루틴이 없습니다.", ephemeral=True)
            except Exception:
                pass
            return

        view = TodayCheckinView(display, ld.isoformat())
        try:
            self.bot.add_view(view)
        except Exception as e:
            print("bot.add_view 등록 실패:", type(e).__name__, e)

        msg_content = f"{self._format_display_date(ld)} 일일 루틴 진행 상태입니다!"

        # 첫 응답으로 채널 메시지를 시도 (response.send_message)
        try:
            if not itx.response.is_done():
                await itx.response.send_message(content=msg_content, view=view, ephemeral=False)
                self.last_checkin_message[(user_id, ld.isoformat())] = {"channel_id": itx.channel.id if itx.channel else 0, "message_id": 0}
                return
        except Exception as e:
            print("response.send_message 전송 실패, followup/DM 폴백:", e)

        # 이미 응답이 된 상태거나 위에서 실패한 경우: followup 또는 DM 폴백
        try:
            msg = await itx.followup.send(content=msg_content, view=view, ephemeral=False)
            self.last_checkin_message[(user_id, ld.isoformat())] = {"channel_id": msg.channel.id, "message_id": msg.id}
            return
        except Exception as e:
            print("followup 전송 실패, DM 시도:", e)

        try:
            dm = await itx.user.send(content=msg_content, view=view)
            self.last_checkin_message[(user_id, ld.isoformat())] = {"channel_id": dm.channel.id, "message_id": dm.id}
        except Exception as e:
            print("DM 전송 실패, 최종 실패로 처리:", e)


    async def handle_toggle_button(self, itx: discord.Interaction, rid: int, yyyymmdd: str):
        # 상태 순환: 미완료 -> 완료 -> 스킵 -> 미달성
        await itx.response.defer()
        user_id = str(itx.user.id)

        try:
            ci = await checkin_repo.get_checkin(rid, yyyymmdd)
        except Exception as e:
            print("get_checkin 에러:", e)
            await itx.followup.send("상태 조회 중 오류가 발생했습니다.", ephemeral=True)
            return

        try:
            if not ci or (not ci.get("checked_at") and not ci.get("skipped")):
                # 미완료 -> 완료
                await checkin_repo.upsert_checkin_done(rid, user_id, yyyymmdd)
                new_status = "완료"
            elif ci.get("checked_at"):
                # 완료 -> 스킵
                await checkin_repo.skip_checkin(rid, user_id, yyyymmdd, reason="(사용자 버튼 스킵)")
                new_status = "스킵"
            elif ci.get("skipped"):
                # 스킵 -> 미완료
                await checkin_repo.clear_checkin(rid, yyyymmdd)
                new_status = "미완료"
            else:
                await checkin_repo.clear_checkin(rid, yyyymmdd)
                new_status = "미완료"
        except Exception as e:
            print("handle_toggle_button DB 에러:", e)
            await itx.followup.send("DB 처리 중 오류가 발생했습니다.", ephemeral=True)
            return

        key = (user_id, yyyymmdd)
        try:
            # 최신 상태 기준으로 다시 뷰 구성
            now = now_kst()
            routines = await routine_repo.prepare_checkin_for_date(user_id, now)
            try:
                ld_date = date.fromisoformat(str(yyyymmdd))
            except Exception:
                ld_date = yyyymmdd
            ld = ld_date

            display = []
            for r in routines:
                try:
                    if await is_valid_day(user_id, r.get("weekend_mode", "weekday"), ld):
                        ci2 = await checkin_repo.get_checkin(r["id"], ld)
                        if ci2 and ci2.get("skipped"):
                            emoji = "➡️"
                        elif ci2 and ci2.get("checked_at"):
                            emoji = "✅"
                        else:
                            emoji = "❌"
                        display.append({"id": r["id"], "name": f"{emoji} {r['name']}"})
                except Exception:
                    continue

            if not display:
                print(f"handle_toggle_button: rebuilt display is empty, skipping message update (key={key})")
                return

            new_view = TodayCheckinView(display, ld.isoformat() if hasattr(ld, "isoformat") else str(ld))
            try:
                self.bot.add_view(new_view)
            except Exception as e:
                print("bot.add_view 등록 실패(갱신 뷰):", type(e).__name__, e)

            info = self.last_checkin_message.get(key)
            if info:
                try:
                    ch = await self.bot.fetch_channel(info["channel_id"])
                    msg = await ch.fetch_message(info["message_id"])
                except Exception as e:
                    print("기존 메시지 조회 실패:", type(e).__name__, e)
                    # 메시지 정보를 못 찾으면 우선 같은 채널에 새로 전송을 시도하고, 실패 시 ephemeral -> DM 순서로 시도
                    # 2. 삭제 후 재전송은 이 케이스에선 대상 메시지가 없어 생략됨
                    try:
                        new_msg = await itx.channel.send(
                            content=f"{self._format_display_date(ld)} 일일 루틴 진행 상태입니다!",
                            view=new_view,
                        )
                        self.last_checkin_message[key] = {"channel_id": new_msg.channel.id, "message_id": new_msg.id}
                        print("기존 메시지 조회 실패 후, 채널에 새 메시지 재전송 성공")
                    except Exception as e_send:
                        print("기존 메시지 조회 실패 후, 채널 재전송 실패:", type(e_send).__name__, e_send)
                        try:
                            await itx.followup.send(
                                f"{self._format_display_date(ld)} 일일 루틴 진행 상태입니다!",
                                view=new_view,
                                ephemeral=True,
                            )
                            print("ephemeral 재전송 성공 (조회 실패 케이스)")
                        except Exception as e_ep:
                            print("ephemeral 재전송 실패 (조회 실패 케이스), DM 시도:", type(e_ep).__name__, e_ep)
                            try:
                                dm = await itx.user.send(
                                    content=f"{self._format_display_date(ld)} 일일 루틴 진행 상태입니다!",
                                    view=new_view,
                                )
                                self.last_checkin_message[key] = {"channel_id": dm.channel.id, "message_id": dm.id}
                                print("DM 재전송 성공 (조회 실패 케이스)")
                            except Exception as e_dm:
                                print("DM 재전송 실패 (조회 실패 케이스):", type(e_dm).__name__, e_dm)
                else:
                    # 1. 기존 메시지 edit 시도
                    try:
                        await msg.edit(
                            content=f"{self._format_display_date(ld)} 일일 루틴 진행 상태입니다!",
                            view=new_view,
                        )
                        print("기존 메시지 edit 성공")
                    except Exception as e:
                        print("기존 메시지 edit 실패, 삭제 후 재전송 시도:", type(e).__name__, e)
                        # 2. 삭제 후 같은 채널에 재전송 시도
                        try:
                            try:
                                await msg.delete()
                            except Exception as e_del:
                                print("기존 메시지 삭제 실패(무시):", type(e_del).__name__, e_del)
                            new_msg = await ch.send(
                                content=f"{self._format_display_date(ld)} 일일 루틴 진행 상태입니다!",
                                view=new_view,
                            )
                            self.last_checkin_message[key] = {"channel_id": new_msg.channel.id, "message_id": new_msg.id}
                            print("삭제 후 같은 채널 재전송 성공")
                        except Exception as e_send:
                            print("삭제 후 같은 채널 재전송 실패, 임페리얼 전송 시도:", type(e_send).__name__, e_send)
                            # 3. 임페리얼(followup, ephemeral=True) 전송 시도
                            try:
                                await itx.followup.send(
                                    f"{self._format_display_date(ld)} 일일 루틴 진행 상태입니다!",
                                    view=new_view,
                                    ephemeral=True,
                                )
                                print("임페리얼 재전송 성공")
                            except Exception as e_ep:
                                print("임페리얼 재전송 실패, DM 전송 시도:", type(e_ep).__name__, e_ep)
                                # 4. DM 전송 시도
                                try:
                                    dm = await itx.user.send(
                                        content=f"{self._format_display_date(ld)} 일일 루틴 진행 상태입니다!",
                                        view=new_view,
                                    )
                                    self.last_checkin_message[key] = {"channel_id": dm.channel.id, "message_id": dm.id}
                                    print("DM 재전송 성공")
                                except Exception as e_dm:
                                    print("DM 재전송 실패:", type(e_dm).__name__, e_dm)
            else:
                # last_checkin_message 기록이 없는 경우: 우선 같은 채널에 새로 전송, 실패 시 임페리얼, 그 다음 DM 순서
                try:
                    if itx.channel:
                        new_msg = await itx.channel.send(
                            content=f"{self._format_display_date(ld)} 일일 루틴 진행 상태입니다!",
                            view=new_view,
                        )
                        self.last_checkin_message[key] = {"channel_id": new_msg.channel.id, "message_id": new_msg.id}
                        print("last_checkin_message 없음: 채널 새 전송 성공")
                        return
                except Exception as e_ch:
                    print("last_checkin_message 없음: 채널 새 전송 실패, 임페리얼 시도:", type(e_ch).__name__, e_ch)

                try:
                    await itx.followup.send(
                        f"{self._format_display_date(ld)} 일일 루틴 진행 상태입니다!",
                        view=new_view,
                        ephemeral=True,
                    )
                    print("last_checkin_message 없음: 임페리얼 전송 성공")
                except Exception as e_ep:
                    print("last_checkin_message 없음: 임페리얼 전송 실패, DM 시도:", type(e_ep).__name__, e_ep)
                    try:
                        dm = await itx.user.send(
                            content=f"{self._format_display_date(ld)} 일일 루틴 진행 상태입니다!",
                            view=new_view,
                        )
                        self.last_checkin_message[key] = {"channel_id": dm.channel.id, "message_id": dm.id}
                        print("last_checkin_message 없음: DM 전송 성공")
                    except Exception as e_dm:
                        print("last_checkin_message 없음: DM 전송 최종 실패:", type(e_dm).__name__, e_dm)
        except Exception as e:
            print("handle_toggle_button 전체 처리 중 예기치 못한 에러:", type(e).__name__, e)
            try:
                await itx.followup.send(
                    f"상태는 '{new_status}'로 변경되었지만 메시지 갱신 중 오류가 발생했습니다.",
                    ephemeral=True,
                )
            except Exception:
                pass

async def setup(bot: commands.Bot):
    await bot.add_cog(RoutineCog(bot))
