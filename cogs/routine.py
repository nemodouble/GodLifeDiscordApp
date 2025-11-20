import discord
from discord.ext import commands
from typing import Dict, Tuple, Any, List
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

    # ------------------------ 내부 유틸 메서드 ------------------------

    async def _build_display_items(self, user_id: str, target_day: Any, now=None) -> List[Dict[str, Any]]:
        """주어진 날짜의 루틴 체크인 표시 데이터를 구성합니다.

        - is_valid_day 필터 적용
        - 체크인 상태에 따라 이모지(❌/✅/➡️) 부여
        """
        if now is None:
            now = now_kst()

        try:
            routines = await routine_repo.prepare_checkin_for_date(user_id, now)
        except Exception as e:
            # 상위에서 처리할 수 있도록 예외를 다시 올립니다.
            print("prepare_checkin_for_date 에러 (internal):", e)
            raise

        # target_day가 date 객체가 아니면 가능한 경우 date로 변환
        if hasattr(target_day, "isoformat"):
            day_for_repo = target_day.isoformat()
        else:
            day_for_repo = str(target_day)

        display: List[Dict[str, Any]] = []
        for r in routines:
            try:
                if await is_valid_day(user_id, r.get("weekend_mode", "weekday"), target_day):
                    try:
                        ci = await checkin_repo.get_checkin(r["id"], day_for_repo)
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
                print("is_valid_day 체크 중 오류 (internal):", e)
                continue

        return display

    def _create_today_checkin_view(self, display: List[Dict[str, Any]], ld: Any) -> TodayCheckinView:
        """주어진 display 목록과 날짜로 TodayCheckinView 인스턴스를 생성하고 bot에 등록합니다."""
        day_str = ld.isoformat() if hasattr(ld, "isoformat") else str(ld)
        view = TodayCheckinView(display, day_str)
        try:
            self.bot.add_view(view)
        except Exception as e:
            print("bot.add_view 등록 실패:", type(e).__name__, e)
        return view

    async def _send_or_followup_error(self, itx: discord.Interaction, message: str):
        """interaction 응답 상태에 따라 에러 메시지를 전송합니다."""
        try:
            if not itx.response.is_done():
                await itx.response.send_message(message, ephemeral=True)
            else:
                await itx.followup.send(message, ephemeral=True)
        except Exception as e2:
            print("_send_or_followup_error 실패:", type(e2).__name__, e2)

    async def _record_last_message(self, user_id: str, day_str: str, msg: discord.Message):
        self.last_checkin_message[(user_id, day_str)] = {
            "channel_id": msg.channel.id,
            "message_id": msg.id,
        }

    async def _send_checkin_panel_primary(self, itx: discord.Interaction, user_id: str, ld: Any, view: TodayCheckinView) -> bool:
        """1차: original response로 패널 전송 시도.

        성공 시 last_checkin_message를 기록하고 True 반환, 실패 시 False.
        """
        msg_content = f"{self._format_display_date(ld)} 일일 루틴 진행 상태입니다!"
        try:
            if not itx.response.is_done():
                msg = await itx.response.send_message(content=msg_content, view=view, ephemeral=False)
                try:
                    if not isinstance(msg, discord.Message):
                        msg = await itx.original_response()
                except Exception:
                    msg = await itx.original_response()

                await self._record_last_message(user_id, ld.isoformat(), msg)
                print("open_today_checkin_list: original response로 패널 전송 및 last_checkin_message 저장 성공")
                return True
        except Exception as e:
            print("open_today_checkin_list: response.send_message 실패, followup/채널로 폴백:", type(e).__name__, e)
        return False

    async def _send_checkin_panel_fallback(self, itx: discord.Interaction, user_id: str, ld: Any, view: TodayCheckinView):
        """2차: followup 또는 채널/DM으로 패널 전송."""
        msg_content = f"{self._format_display_date(ld)} 일일 루틴 진행 상태입니다!"
        try:
            if itx.response.is_done():
                msg = await itx.followup.send(content=msg_content, view=view, ephemeral=False)
            else:
                await itx.response.defer(ephemeral=False)
                channel = itx.channel or await itx.user.create_dm()
                msg = await channel.send(content=msg_content, view=view)

            await self._record_last_message(user_id, ld.isoformat(), msg)
            print("open_today_checkin_list: 폴백 전송 및 last_checkin_message 저장 성공")
        except Exception as e:
            print("open_today_checkin_list: 폴백 전송 최종 실패:", type(e).__name__, e)

    async def _toggle_checkin_state(self, rid: int, user_id: str, yyyymmdd: str) -> str:
        """체크인 상태를 토글하고 새 상태 문자열을 반환합니다."""
        try:
            ci = await checkin_repo.get_checkin(rid, yyyymmdd)
        except Exception as e:
            print("get_checkin 에러:", e)
            raise

        try:
            if not ci or (not ci.get("checked_at") and not ci.get("skipped")):
                await checkin_repo.upsert_checkin_done(rid, user_id, yyyymmdd)
                return "완료"
            if ci.get("checked_at"):
                await checkin_repo.skip_checkin(rid, user_id, yyyymmdd, reason="(사용자 버튼 스킵)")
                return "스킵"
            if ci.get("skipped"):
                await checkin_repo.clear_checkin(rid, yyyymmdd)
                return "미완료"

            await checkin_repo.clear_checkin(rid, yyyymmdd)
            return "미완료"
        except Exception as e:
            print("handle_toggle_button DB 에러:", e)
            raise

    async def _rebuild_and_send_updated_panel(self, itx: discord.Interaction, user_id: str, yyyymmdd: str):
        """토글 후 최신 상태로 패널을 다시 구성하고 메시지를 갱신/재전송합니다."""
        key = (user_id, yyyymmdd)

        now = now_kst()
        try:
            try:
                ld_date = date.fromisoformat(str(yyyymmdd))
            except Exception:
                ld_date = yyyymmdd
            ld = ld_date

            display = await self._build_display_items(user_id, ld, now)

            if not display:
                print(f"handle_toggle_button: rebuilt display is empty, skipping message update (key={key})")
                try:
                    await itx.followup.send("갱신할 체크인 대상이 없습니다.", ephemeral=True)
                except Exception as e2:
                    print("handle_toggle_button: display 없음 안내 실패:", type(e2).__name__, e2)
                return

            new_view = self._create_today_checkin_view(display, ld)
            msg_content = f"{self._format_display_date(ld)} 일일 루틴 진행 상태입니다!"

            info = self.last_checkin_message.get(key)
            if info:
                await self._update_existing_message_with_fallback(itx, key, info, msg_content, new_view)
            else:
                await self._send_new_message_with_fallback(itx, key, msg_content, new_view)

        except Exception as e:
            print("handle_toggle_button 전체 처리 중 예기치 못한 에러:", type(e).__name__, e)
            raise

    async def _update_existing_message_with_fallback(self, itx: discord.Interaction, key, info, msg_content, new_view):
        """기존 메시지 edit를 우선 시도하고 실패 시 다양한 폴백 경로를 사용합니다."""
        user_id, yyyymmdd = key
        try:
            ch = await self.bot.fetch_channel(info["channel_id"])
            msg = await ch.fetch_message(info["message_id"])
        except Exception as e:
            print("기존 메시지 조회 실패:", type(e).__name__, e)
            # 메시지 정보를 못 찾으면 우선 같은 채널에 새로 전송을 시도하고, 실패 시 임페리얼 -> DM 순서로 시도
            try:
                if itx.channel:
                    new_msg = await itx.channel.send(content=msg_content, view=new_view)
                    await self._record_last_message(user_id, yyyymmdd, new_msg)
                    print("기존 메시지 조회 실패 후, 채널에 새 메시지 재전송 성공")
                    return
            except Exception as e_send:
                print("기존 메시지 조회 실패 후, 채널 재전송 실패:", type(e_send).__name__, e_send)

            try:
                await itx.followup.send(msg_content, view=new_view, ephemeral=True)
                print("ephemeral 재전송 성공 (조회 실패 케이스)")
                return
            except Exception as e_ep:
                print("ephemeral 재전송 실패 (조회 실패 케이스), DM 시도:", type(e_ep).__name__, e_ep)
                try:
                    dm = await itx.user.send(content=msg_content, view=new_view)
                    await self._record_last_message(user_id, yyyymmdd, dm)
                    print("DM 재전송 성공 (조회 실패 케이스)")
                except Exception as e_dm:
                    print("DM 재전송 실패 (조회 실패 케이스):", type(e_dm).__name__, e_dm)
            return

        # 1. 기존 메시지 edit 시도
        try:
            await msg.edit(content=msg_content, view=new_view)
            print("기존 메시지 edit 성공")
        except Exception as e:
            print("기존 메시지 edit 실패, 삭제 후 재전송 시도:", type(e).__name__, e)
            # 2. 삭제 후 같은 채널에 재전송 시도
            try:
                try:
                    await msg.delete()
                except Exception as e_del:
                    print("기존 메시지 삭제 실패(무시):", type(e_del).__name__, e_del)
                new_msg = await ch.send(content=msg_content, view=new_view)
                await self._record_last_message(user_id, yyyymmdd, new_msg)
                print("삭제 후 같은 채널 재전송 성공")
            except Exception as e_send:
                print("삭제 후 같은 채널 재전송 실패, 임페리얼 전송 시도:", type(e_send).__name__, e_send)
                try:
                    await itx.followup.send(msg_content, view=new_view, ephemeral=True)
                    print("임페리얼 재전송 성공")
                except Exception as e_ep:
                    print("임페리얼 재전송 실패, DM 전송 시도:", type(e_ep).__name__, e_ep)
                    try:
                        dm = await itx.user.send(content=msg_content, view=new_view)
                        await self._record_last_message(user_id, yyyymmdd, dm)
                        print("DM 재전송 성공")
                    except Exception as e_dm:
                        print("DM 재전송 실패:", type(e_dm).__name__, e_dm)

    async def _send_new_message_with_fallback(self, itx: discord.Interaction, key, msg_content, new_view):
        """last_checkin_message 기록이 없는 경우 새 메시지 전송 흐름."""
        user_id, yyyymmdd = key
        try:
            if itx.channel:
                new_msg = await itx.channel.send(content=msg_content, view=new_view)
                await self._record_last_message(user_id, yyyymmdd, new_msg)
                print("last_checkin_message 없음: 채널 새 전송 성공")
                return
        except Exception as e_ch:
            print("last_checkin_message 없음: 채널 새 전송 실패, 임페리얼 시도:", type(e_ch).__name__, e_ch)

        try:
            await itx.followup.send(msg_content, view=new_view, ephemeral=True)
            print("last_checkin_message 없음: 임페리얼 전송 성공")
        except Exception as e_ep:
            print("last_checkin_message 없음: 임페리얼 전송 실패, DM 시도:", type(e_ep).__name__, e_ep)
            try:
                dm = await itx.user.send(content=msg_content, view=new_view)
                await self._record_last_message(user_id, yyyymmdd, dm)
                print("last_checkin_message 없음: DM 전송 성공")
            except Exception as e_dm:
                print("last_checkin_message 없음: DM 전송 최종 실패:", type(e_dm).__name__, e_dm)

    # ------------------------ 공개 메서드 ------------------------

    async def open_today_checkin_list(self, itx: discord.Interaction):
        """오늘 일일 루틴 진행 상태 패널을 전송한다.

        - Interaction의 original response 메시지로 패널을 전송
        - 필요 시 followup 또는 DM으로만 보조 메시지를 사용
        """
        user_id = str(itx.user.id)
        now = now_kst()
        ld = local_day(now)

        try:
            display = await self._build_display_items(user_id, ld, now)
        except Exception:
            await self._send_or_followup_error(itx, "루틴 목록을 불러오는 중 오류가 발생했습니다.")
            return

        if not display:
            await self._send_or_followup_error(itx, "오늘 체크인 대상 루틴이 없습니다.")
            return

        view = self._create_today_checkin_view(display, ld)

        # 1차 시도: original response로 패널 전송
        primary_sent = await self._send_checkin_panel_primary(itx, user_id, ld, view)
        if primary_sent:
            return

        # 2차 시도: 이미 응답이 된 상태거나 위에서 실패한 경우 followup 또는 채널/DM으로 전송
        await self._send_checkin_panel_fallback(itx, user_id, ld, view)

    async def handle_toggle_button(self, itx: discord.Interaction, rid: int, yyyymmdd: str):
        """체크인 토글 버튼 핸들러

        - 상태 순환: 미완료 -> 완료 -> 스킵 -> 미완료
        - Interaction의 original 메시지를 가능하면 수정(edit)하고,
          실패 시 채널/임페리얼/DM 순으로 새 메시지를 전송
        """
        if not itx.response.is_done():
            try:
                await itx.response.defer(ephemeral=True)
            except Exception as e:
                print("handle_toggle_button: response.defer 실패:", type(e).__name__, e)

        user_id = str(itx.user.id)

        try:
            new_status = await self._toggle_checkin_state(rid, user_id, yyyymmdd)
        except Exception:
            try:
                await itx.followup.send("상태 조회/DB 처리 중 오류가 발생했습니다.", ephemeral=True)
            except Exception as e2:
                print("handle_toggle_button: 상태/DB 오류 응답 실패:", type(e2).__name__, e2)
            return

        try:
            await self._rebuild_and_send_updated_panel(itx, user_id, yyyymmdd)
        except Exception as e:
            print("handle_toggle_button 메시지 갱신 중 오류:", type(e).__name__, e)
            try:
                await itx.followup.send(
                    f"상태는 '{new_status}'로 변경되었지만 메시지 갱신 중 오류가 발생했습니다.",
                    ephemeral=True,
                )
            except Exception:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(RoutineCog(bot))
