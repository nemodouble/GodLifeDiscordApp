import discord
from discord.ext import commands
from typing import Dict, Tuple, Any, List
from datetime import date, datetime

from repos import routine_repo, checkin_repo, goal_repo, user_settings_repo
from domain.time_utils import now_kst, local_day, is_valid_day
from ui.views import TodayCheckinView, GoalSuggestView


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

    async def _delete_existing_checkin_messages_in_channel(self, channel: Any, ld: Any) -> None:
        """해당 채널에서 오늘자 체크인 패널(yy-mm-dd 로 시작하는 bot 메시지)을 찾아 삭제.

        - 너무 오래된 메시지까지 뒤지지 않도록 limit/after 를 적절히 사용
        - 삭제 실패는 로그만 출력하고 무시
        """
        prefix = f"{self._format_display_date(ld)} 일일 루틴 진행 상태입니다!"
        # print(f"[RoutineCog] delete_existing_checkin_messages_in_channel: channel={getattr(channel, 'id', None)}, prefix='{prefix}'")

        # 채널이 텍스트 채널/쓰레드가 아닌 DM 등의 경우에도 history 는 대부분 지원하지만,
        # 혹시 모를 타입 문제를 피하기 위해 getattr 사용
        history = getattr(channel, "history", None)
        if history is None:
            return

        # 너무 과도하게 오래된 메시지를 보지 않도록 200개 정도만 조회
        try:
            async for msg in channel.history(limit=200):
                try:
                    if msg.author == channel.guild.me if hasattr(channel, "guild") and channel.guild else msg.author.bot:
                        if isinstance(msg.content, str) and msg.content.startswith(prefix):
                            try:
                                await msg.delete()
                            except Exception as e_del:
                                print("_delete_existing_checkin_messages_in_channel: delete 실패:", type(e_del).__name__, e_del)
                except Exception as e_inner:
                    print("_delete_existing_checkin_messages_in_channel: 메시지 검사 중 오류:", type(e_inner).__name__, e_inner)
                    continue
        except Exception as e_hist:
            print("_delete_existing_checkin_messages_in_channel: history 조회 실패:", type(e_hist).__name__, e_hist)

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

        - target_day 기준으로 루틴 목록을 조회해야 과거 날짜 갱신 시 오늘 루틴이 섞이지 않습니다.
        - is_valid_day 필터 적용 및 체크인 상태(❌/✅/➡️) 반영.
        """
        if now is None:
            now = now_kst()

        # target_day 를 date 객체로 최대한 보정 (실패 시, local_day(now) 사용)
        if isinstance(target_day, date):
            ld = target_day
        else:
            try:
                ld = date.fromisoformat(str(target_day))
            except Exception:
                ld = local_day(now)

        try:
            # 🔁 기존에는 `prepare_checkin_for_date(user_id, now)` 를 사용해서
            # 항상 "오늘" 기준 루틴 목록을 가져오고 있었습니다.
            # 과거 날짜 패널을 갱신할 때도 오늘 기준 루틴이 사용되는 버그의 원인이므로,
            # 해당 날짜(ld) 기준으로 적용 가능한 루틴을 직접 조회합니다.
            routines = await routine_repo.routines_applicable_for_date(user_id, ld)
        except Exception as e:
            print("routines_applicable_for_date 에러 (internal):", e)
            raise

        # 체크인 레코드용 날짜 문자열
        day_for_repo = ld.isoformat()

        display: List[Dict[str, Any]] = []
        for r in routines:
            try:
                # weekend_mode / 요일 규칙이 변경될 수 있으므로 is_valid_day 로 한 번 더 확인
                if await is_valid_day(user_id, r.get("weekend_mode", "weekday"), ld):
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
        except Exception:
            # 에러 응답도 실패한 경우는 콘솔에만 남겨도 충분하므로 조용히 무시
            pass

    async def _record_last_message(self, user_id: str, day_str: str, msg: discord.Message):
        self.last_checkin_message[(user_id, day_str)] = {
            "channel_id": msg.channel.id,
            "message_id": msg.id,
        }

    async def _build_goal_suggestion_message(self, user_id: str, today_ld) -> str | None:
        """일/주/월 목표 제안 및 기한이 지난 목표 언급 메시지 생성.

        - today_ld: date 객체 (local_day 기준)
        - 주간 목표: 월요일에 제안
        - 월간 목표: 매달 첫 주 월요일에 제안 (1~7일 사이의 월요일)
        """
        # today_ld 를 date 로 보정
        if not isinstance(today_ld, date):
            try:
                if hasattr(today_ld, "isoformat"):
                    today_ld = today_ld
                else:
                    today_ld = date.fromisoformat(str(today_ld))
            except Exception:
                return None

        pieces: List[str] = []

        # 1) 기간이 지난 목표(마감 < 오늘) 중 아직 진행 중(active=1)인 것 간단 언급
        try:
            goals = await goal_repo.list_active_goals_for_user(user_id)
        except Exception as e:
            print("_build_goal_suggestion_message: list_active_goals_for_user 에러:", e)
            goals = []

        overdue_titles: List[str] = []
        today_iso = today_ld.isoformat()
        for g in goals:
            ddl = g.get("deadline")
            if not ddl:
                continue
            try:
                if str(ddl) < today_iso:
                    overdue_titles.append(g.get("title") or f"목표#{g.get('id')}")
            except Exception:
                continue

        if overdue_titles:
            pieces.append("기한이 지난 목표가 있어요. 한 번 정리해보면 좋을 것 같아요.")

        # 2) 오늘 설정할 일간/주간/월간 목표 간략 제안
        weekday = today_ld.weekday()  # 0=월
        day_of_month = today_ld.day

        pieces.append("오늘 집중하고 싶은 목표가 있다면 하나 정해 두고 진행해보세요.")

        if weekday == 0:
            pieces.append("이번 주에 꼭 이루고 싶은 한 가지를 정해 두면 도움이 될 수 있어요.")
            if 1 <= day_of_month <= 7:
                pieces.append("이번 달 안에 이루고 싶은 큰 목표도 하나 생각해 보면 좋습니다.")

        if not pieces:
            return None

        return "\n".join(pieces)

    async def _should_suggest_goals(self, user_id: str) -> bool:
        """user_settings 를 조회해 체크인 시 목표 제안을 보여줄지 여부를 반환."""
        try:
            settings = await user_settings_repo.get_user_settings(user_id)
        except Exception as e:
            print("_should_suggest_goals: get_user_settings 에러:", e)
            return True
        if settings is None:
            return True
        v = settings.get("suggest_goals_on_checkin", 1)
        try:
            return bool(int(v))
        except Exception:
            return bool(v)

    async def _send_goal_suggestion_ephemeral(self, itx: discord.Interaction, user_id: str, today_ld) -> None:
        """체크인 패널과 별개로, 목표 제안/마감 지난 목표 안내를 에페메랄로 전송.

        - 내용: 텍스트 + GoalSuggestView(목표 추가 버튼)
        """
        # 설정 확인
        if not await self._should_suggest_goals(user_id):
            return

        msg = await self._build_goal_suggestion_message(user_id, today_ld)
        if not msg:
            return

        # today_ld를 ISO 문자열로 전달해 일간 목표 마감일 기본값으로 활용
        try:
            day_str = today_ld.isoformat() if hasattr(today_ld, "isoformat") else str(today_ld)
        except Exception:
            day_str = None

        try:
            view = GoalSuggestView(target_day=day_str)
            await itx.followup.send(msg, view=view, ephemeral=True)
        except Exception as e:
            print("_send_goal_suggestion_ephemeral 실패:", type(e).__name__, e)

    async def _send_checkin_panel_primary(self, itx: discord.Interaction, user_id: str, ld: Any, view: TodayCheckinView) -> bool:
        """1차: original response로 체크인 패널 전송 시도.

        - 성공 시 last_checkin_message를 기록하고 True 반환
        - 실패 시 False 반환 (fallback 경로에서 처리)
        """
        msg_content = f"{self._format_display_date(ld)} 일일 루틴 진행 상태입니다!"
        # print(f"[RoutineCog] _send_checkin_panel_primary start: user_id={user_id}, ld={ld}, channel={getattr(itx.channel, 'id', None)}")
        try:
            try:
                channel = itx.channel or (await itx.user.create_dm())
                # print(f"[RoutineCog] _send_checkin_panel_primary: resolved channel={getattr(channel, 'id', None)}")
                if channel is not None:
                    await self._delete_existing_checkin_messages_in_channel(channel, ld)
            except Exception as e_del:
                print("_send_checkin_panel_primary: 기존 패널 삭제 중 오류(무시):", type(e_del).__name__, e_del)

            if not itx.response.is_done():
                # print("[RoutineCog] _send_checkin_panel_primary: sending original response")
                msg = await itx.response.send_message(content=msg_content, view=view, ephemeral=False)
                try:
                    if not isinstance(msg, discord.Message):
                        msg = await itx.original_response()
                except Exception:
                    msg = await itx.original_response()

                await self._record_last_message(user_id, ld.isoformat(), msg)
                # print("open_today_checkin_list: original response로 패널 전송 및 last_checkin_message 저장 성공")

                # 패널 전송 후 별도의 에페메랄 목표 제안 메시지 전송
                await self._send_goal_suggestion_ephemeral(itx, user_id, ld)
                return True
            else:
                # print("[RoutineCog] _send_checkin_panel_primary: interaction.response already done, skip primary")
                pass
        except Exception as e:
            print("_send_checkin_panel_primary: response.send_message 실패, fallback 필요:", type(e).__name__, e)
        return False

    async def _send_checkin_panel_fallback(self, itx: discord.Interaction, user_id: str, ld: Any, view: TodayCheckinView) -> None:
        """2차: followup 또는 채널/DM으로 체크인 패널 전송.

        original response 사용이 불가능하거나 1차 시도가 실패한 경우 호출됩니다.
        """
        msg_content = f"{self._format_display_date(ld)} 일일 루틴 진행 상태입니다!"
        # print(f"[RoutineCog] _send_checkin_panel_fallback start: user_id={user_id}, ld={ld}, channel={getattr(itx.channel, 'id', None)}")
        try:
            # fallback 경로에서도 동일 채널(또는 DM)에 기존 오늘자 패널이 있으면 먼저 삭제
            try:
                channel = itx.channel or (await itx.user.create_dm())
                if channel is not None:
                    await self._delete_existing_checkin_messages_in_channel(channel, ld)
            except Exception as e_del:
                print("_send_checkin_panel_fallback: 기존 패널 삭제 중 오류(무시):", type(e_del).__name__, e_del)

            if itx.response.is_done():
                msg = await itx.followup.send(content=msg_content, view=view, ephemeral=False)
            else:
                await itx.response.defer(ephemeral=False)
                channel = itx.channel or await itx.user.create_dm()
                msg = await channel.send(content=msg_content, view=view)

            await self._record_last_message(user_id, ld.isoformat(), msg)
            # print("open_today_checkin_list: fallback 전송 및 last_checkin_message 저장 성공")
        except Exception as e:
            print("_send_checkin_panel_fallback: 패널 전송 최종 실패:", type(e).__name__, e)

        # 패널 전송 성공/실패와 관계없이 목표 제안 에페메랄은 시도
        await self._send_goal_suggestion_ephemeral(itx, user_id, ld)

    async def _toggle_checkin_state(self, rid: int, user_id: str, yyyymmdd: str) -> str:
        """체크인 상태를 토글하고 새 상태 문자열을 반환합니다.

        상태 순환 규칙:
        - (기록 없음 또는 미완료) -> 완료
        - 완료(checked_at 있음) -> 스킵
        - 스킵(skipped=1) -> 미완료(모든 상태 클리어)
        그 외에는 방어적으로 미완료로 초기화합니다.
        """
        try:
            ci = await checkin_repo.get_checkin(rid, yyyymmdd)
        except Exception as e:
            print("_toggle_checkin_state: get_checkin 에러:", e)
            raise

        try:
            # 1) 아직 기록이 없거나, checked_at/skip 이 모두 비어 있으면 -> 완료 처리
            if not ci or (not ci.get("checked_at") and not ci.get("skipped")):
                await checkin_repo.upsert_checkin_done(rid, user_id, yyyymmdd)
                return "완료"

            # 2) 완료 상태 -> 스킵으로 전환
            if ci.get("checked_at"):
                await checkin_repo.skip_checkin(rid, user_id, yyyymmdd, reason="(사용자 버튼 스킵)")
                return "스킵"

            # 3) 스킵 상태 -> 미완료(클리어)
            if ci.get("skipped"):
                await checkin_repo.clear_checkin(rid, yyyymmdd)
                return "미완료"

            # 4) 기타 애매한 상태도 안전하게 미완료로 초기화
            await checkin_repo.clear_checkin(rid, yyyymmdd)
            return "미완료"
        except Exception as e:
            print("_toggle_checkin_state: DB 토글 처리 중 에러:", e)
            raise

    async def _rebuild_and_send_updated_panel(self, itx: discord.Interaction, user_id: str, yyyymmdd: str):
        """토글 후 최신 상태로 패널을 다시 구성하고 메시지를 갱신/재전송합니다.

        - last_checkin_message 에 저장된 메시지가 있으면 우선 수정(edit)을 시도
        - 실패 시 같은 채널/임페메랄/DM 순으로 새로운 메시지를 전송
        """
        key = (user_id, yyyymmdd)
        now = now_kst()

        # yyyymmdd 문자열을 date 로 복원 시도 (실패 시 그대로 사용)
        try:
            ld = date.fromisoformat(str(yyyymmdd))
        except Exception:
            ld = yyyymmdd

        try:
            display = await self._build_display_items(user_id, ld, now)
        except Exception as e:
            print("_rebuild_and_send_updated_panel: _build_display_items 에러:", e)
            try:
                await itx.followup.send("루틴 목록을 다시 불러오는 중 오류가 발생했습니다.", ephemeral=True)
            except Exception as e2:
                print("_rebuild_and_send_updated_panel: 에러 안내 실패:", type(e2).__name__, e2)
            return

        if not display:
            print(f"_rebuild_and_send_updated_panel: display 비어 있음, key={key}")
            try:
                await itx.followup.send("갱신할 체크인 대상이 없습니다.", ephemeral=True)
            except Exception as e2:
                print("_rebuild_and_send_updated_panel: display 없음 안내 실패:", type(e2).__name__, e2)
            return

        new_view = self._create_today_checkin_view(display, ld)
        msg_content = f"{self._format_display_date(ld)} 일일 루틴 진행 상태입니다!"

        info = self.last_checkin_message.get(key)
        if info:
            await self._update_existing_message_with_fallback(itx, key, info, msg_content, new_view)
        else:
            await self._send_new_message_with_fallback(itx, key, msg_content, new_view)

    async def _update_existing_message_with_fallback(self, itx: discord.Interaction, key, info, msg_content, new_view):
        """기존 메시지 edit를 우선 시도하고 실패 시 다양한 폴백 경로를 사용합니다."""
        user_id, yyyymmdd = key
        try:
            ch = await self.bot.fetch_channel(info["channel_id"])
            msg = await ch.fetch_message(info["message_id"])
        except Exception as e:
            print("_update_existing_message_with_fallback: 기존 메시지 조회 실패:", type(e).__name__, e)
            # 메시지 정보를 못 찾으면 우선 같은 채널에 새로 전송을 시도
            try:
                if itx.channel:
                    new_msg = await itx.channel.send(content=msg_content, view=new_view)
                    await self._record_last_message(user_id, yyyymmdd, new_msg)
                    # print("_update_existing_message_with_fallback: 채널에 새 메시지로 재전송 성공")
                    return
            except Exception as e_send:
                print("_update_existing_message_with_fallback: 채널 재전송 실패:", type(e_send).__name__, e_send)

            # 채널 전송 실패 시 에페메랄/DM 순으로 폴백
            try:
                await itx.followup.send(msg_content, view=new_view, ephemeral=True)
                # print("_update_existing_message_with_fallback: 에페메랄 재전송 성공")
                return
            except Exception as e_ep:
                print("_update_existing_message_with_fallback: 에페메랄 재전송 실패, DM 시도:", type(e_ep).__name__, e_ep)
                try:
                    dm = await itx.user.send(content=msg_content, view=new_view)
                    await self._record_last_message(user_id, yyyymmdd, dm)
                    # print("_update_existing_message_with_fallback: DM 재전송 성공")
                except Exception as e_dm:
                    print("_update_existing_message_with_fallback: DM 재전송 실패:", type(e_dm).__name__, e_dm)
            return

        # 1차: 기존 메시지 edit 시도
        try:
            await msg.edit(content=msg_content, view=new_view)
            # print("_update_existing_message_with_fallback: 기존 메시지 edit 성공")
        except Exception as e:
            print("_update_existing_message_with_fallback: 기존 메시지 edit 실패, 삭제 후 재전송 시도:", type(e).__name__, e)
            # 2차: 삭제 후 같은 채널에 재전송
            try:
                try:
                    await msg.delete()
                except Exception as e_del:
                    print("_update_existing_message_with_fallback: 기존 메시지 삭제 실패(무시):", type(e_del).__name__, e_del)
                new_msg = await ch.send(content=msg_content, view=new_view)
                await self._record_last_message(user_id, yyyymmdd, new_msg)
                # print("_update_existing_message_with_fallback: 삭제 후 같은 채널 재전송 성공")
            except Exception as e_send:
                print("_update_existing_message_with_fallback: 삭제 후 채널 재전송 실패, 에페메랄 시도:", type(e_send).__name__, e_send)
                try:
                    await itx.followup.send(msg_content, view=new_view, ephemeral=True)
                    # print("_update_existing_message_with_fallback: 에페메랄 재전송 성공")
                except Exception as e_ep:
                    print("_update_existing_message_with_fallback: 에페메랄 재전송 실패, DM 시도:", type(e_ep).__name__, e_ep)
                    try:
                        dm = await itx.user.send(content=msg_content, view=new_view)
                        await self._record_last_message(user_id, yyyymmdd, dm)
                        # print("_update_existing_message_with_fallback: DM 재전송 성공")
                    except Exception as e_dm:
                        print("_update_existing_message_with_fallback: DM 재전송 실패:", type(e_dm).__name__, e_dm)

    async def _send_new_message_with_fallback(self, itx: discord.Interaction, key, msg_content, new_view):
        """last_checkin_message 기록이 없는 경우 새 메시지 전송 흐름."""
        user_id, yyyymmdd = key
        try:
            if itx.channel:
                new_msg = await itx.channel.send(content=msg_content, view=new_view)
                await self._record_last_message(user_id, yyyymmdd, new_msg)
                # print("_send_new_message_with_fallback: 채널 새 전송 성공")
                return
        except Exception as e_ch:
            print("_send_new_message_with_fallback: 채널 새 전송 실패, 에페메랄 시도:", type(e_ch).__name__, e_ch)

        try:
            await itx.followup.send(msg_content, view=new_view, ephemeral=True)
            # print("_send_new_message_with_fallback: 에페메랄 전송 성공")
        except Exception as e_ep:
            print("_send_new_message_with_fallback: 에페메랄 전송 실패, DM 시도:", type(e_ep).__name__, e_ep)
            try:
                dm = await itx.user.send(content=msg_content, view=new_view)
                await self._record_last_message(user_id, yyyymmdd, dm)
                # print("_send_new_message_with_fallback: DM 전송 성공")
            except Exception as e_dm:
                print("_send_new_message_with_fallback: DM 전송 실패:", type(e_dm).__name__, e_dm)

    # ------------------------ 공개 메서드 ------------------------

    async def open_today_checkin_list(self, itx: discord.Interaction, target_date: str = None):
        """일일 루틴 진행 상태 패널을 전송한다.

        - target_date: YYYY-MM-DD 형식의 날짜 문자열. None이면 오늘 날짜 사용.
        - Interaction의 original response 메시지로 패널을 전송
        - 필요 시 followup 또는 DM으로만 보조 메시지를 사용
        """
        user_id = str(itx.user.id)
        now = now_kst()

        # target_date 파라미터가 있으면 파싱, 없으면 오늘 날짜 사용
        if target_date:
            try:
                ld = date.fromisoformat(target_date)
            except (ValueError, TypeError):
                await self._send_or_followup_error(itx, "날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식으로 입력해주세요. (예: 2025-01-15)")
                return
        else:
            ld = local_day(now)

        try:
            display = await self._build_display_items(user_id, ld, now)
        except Exception:
            await self._send_or_followup_error(itx, "루틴 목록을 불러오는 중 오류가 발생했습니다.")
            return

        if not display:
            date_msg = "해당 날짜에" if target_date else "오늘"
            await self._send_or_followup_error(itx, f"{date_msg} 체크인 대상 루틴이 없습니다.")
            return

        view = self._create_today_checkin_view(display, ld)

        primary_sent = await self._send_checkin_panel_primary(itx, user_id, ld, view)
        if primary_sent:
            return

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
