from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any

from db.db import connect_db
from domain.time_utils import is_valid_day, local_day, now_kst
from repos import routine_repo


def window_dates(scope: Optional[str], today_local: date) -> Optional[List[date]]:
    """주어진 범위(scope)에 대한 날짜 리스트를 반환.

    scope: '7d' | '30d' | 'all' 또는 None
    반환값: 날짜 리스트 (최근 포함, 역순 아님). 'all'의 경우 None 반환하여 호출자가 동적으로 범위를 계산.

    개선: 리포트를 요청한 오늘(today_local)은 항상 제외하고 과거 날짜만 포함한다.
    """
    if scope == "7d":
        # 오늘 기준 직전 7일 (오늘 제외: today-1 ~ today-7)
        return [today_local - timedelta(days=i) for i in range(1, 8)][::-1]
    if scope == "30d":
        # 오늘 기준 직전 30일 (오늘 제외)
        return [today_local - timedelta(days=i) for i in range(1, 31)][::-1]
    # all -> None
    return None


async def _routine_start_date(routine: Dict[str, Any], today_local: date) -> date:
    """루틴이 실제로 유효해지는 시작일을 반환.

    우선순위:
      1) routine["start_date"] (YYYY-MM-DD)
      2) routine["created_at"] (ISO datetime)
      3) (today_local - 365일)
    """
    # 1) 명시적 start_date 우선
    sd = routine.get("start_date")
    if sd:
        try:
            return datetime.fromisoformat(str(sd)).date()
        except Exception:
            try:
                return date.fromisoformat(str(sd))
            except Exception:
                pass

    # 2) created_at 사용
    created_at = routine.get("created_at")
    if created_at:
        try:
            dt = datetime.fromisoformat(str(created_at))
            return local_day(dt)
        except Exception:
            pass

    # 3) fallback: 1년 전
    return today_local - timedelta(days=365)


async def count_done_days(routine_id: int, dates: Optional[List[date]]) -> Tuple[int, List[date]]:
    """주어진 날짜들 중 완료(checked_at IS NOT NULL, skipped = 0)로 표시된 날짜 수와 날짜 목록 반환.

    dates가 None이면 전체 기록을 대상으로 계산한다.
    반환: (완료일수, 완료일 리스트)
    """
    conn = await connect_db()
    try:
        if dates is None or len(dates) == 0:
            cur = await conn.execute(
                "SELECT local_day FROM routine_checkin WHERE routine_id = ? AND checked_at IS NOT NULL AND skipped = 0",
                (routine_id,),
            )
            rows = await cur.fetchall()
            await cur.close()
            done_days = [datetime.fromisoformat(r["local_day"]).date() if isinstance(r["local_day"], str) else r["local_day"] for r in rows]
            return len(done_days), done_days
        placeholders = ",".join("?" for _ in dates)
        iso_dates = [d.isoformat() for d in dates]
        cur = await conn.execute(
            f"SELECT local_day FROM routine_checkin WHERE routine_id = ? AND local_day IN ({placeholders}) AND checked_at IS NOT NULL AND skipped = 0",
            (routine_id, *iso_dates),
        )
        rows = await cur.fetchall()
        await cur.close()
        done_days = [datetime.fromisoformat(r["local_day"]).date() for r in rows]
        return len(done_days), done_days
    finally:
        await conn.close()


async def count_valid_days(user_id: str, routine: Dict[str, Any], dates: Optional[List[date]]) -> Tuple[int, List[date]]:
    """주어진 날짜들 중 유효한(체크인이 요구되는) 날짜 수와 날짜 목록을 반환.

    정책:
    - is_valid_day(user_id, weekend_mode, d) 가 True여야 함
    - 사용자가 스킵(skipped=1)으로 표시한 날짜는 유효일에서 제외
    - 루틴이 pause 상태인 날짜는 유효일에서 제외 (분모 제거)
    """
    if dates is None:
        return 0, []

    # 루틴 시작일 이전 날짜는 분모에서 제외
    today_local = local_day(now_kst())
    start_date = await _routine_start_date(routine, today_local)
    # dates는 모두 today_local 이전이므로 단순 필터 가능
    dates = [d for d in dates if d >= start_date]
    if not dates:
        return 0, []

    # 미리 DB에서 스킵 정보를 가져와서 파싱
    conn = await connect_db()
    try:
        placeholders = ",".join("?" for _ in dates)
        iso_dates = [d.isoformat() for d in dates]
        cur = await conn.execute(
            f"SELECT local_day, skipped FROM routine_checkin WHERE routine_id = ? AND local_day IN ({placeholders})",
            (routine["id"], *iso_dates),
        )
        rows = await cur.fetchall()
        await cur.close()
        skipped_map = {datetime.fromisoformat(r["local_day"]).date(): bool(r["skipped"]) for r in rows}
    finally:
        await conn.close()

    valid_days: List[date] = []
    for d in dates:
        # pause는 분모에서 제외
        if routine_repo.is_paused_for_day(routine, d):
            continue
        # is_valid_day는 async
        if not await is_valid_day(str(user_id), routine.get("weekend_mode", "weekday"), d):
            continue
        # 사용자가 스킵으로 표시했으면 유효일에서 제외
        if skipped_map.get(d, False):
            continue
        valid_days.append(d)

    return len(valid_days), valid_days


async def _build_date_range(start: date, end: date) -> List[date]:
    """시작일과 종료일 사이의 모든 날짜 리스트를 생성."""
    days: List[date] = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur = cur + timedelta(days=1)
    return days


async def calc_streak(user_id: str, routine: Dict[str, Any]) -> Tuple[int, int]:
    """루틴의 유효일 기준 최대/현재 streak를 계산.

    pause 정책:
    - pause 날짜는 streak 계산에서 유효일로 보지 않고 건너뜀(분모/연속성 모두 제외)
    """
    # 오늘의 local_day
    today = local_day(now_kst())

    # 시작일 결정: 루틴 시작일 헬퍼 사용
    start_date: Optional[date] = await _routine_start_date(routine, today)

    # 전체 날짜 리스트
    all_dates = await _build_date_range(start_date, today)

    # 미리 DB에서 해당 루틴의 체크인 레코드들을 가져옴
    conn = await connect_db()
    try:
        cur = await conn.execute(
            "SELECT local_day, checked_at, skipped FROM routine_checkin WHERE routine_id = ? AND local_day BETWEEN ? AND ?",
            (routine["id"], start_date.isoformat(), today.isoformat()),
        )
        rows = await cur.fetchall()
        await cur.close()
        rec_map = {datetime.fromisoformat(r["local_day"]).date(): {"checked_at": r["checked_at"], "skipped": bool(r["skipped"]) } for r in rows}
    finally:
        await conn.close()

    max_streak = 0
    running = 0
    # 전체 최대 연속 계산(순방향)
    for d in all_dates:
        # pause면 streak/유효일에서 제외
        if routine_repo.is_paused_for_day(routine, d):
            continue
        if not await is_valid_day(str(user_id), routine.get("weekend_mode", "weekday"), d):
            continue
        rec = rec_map.get(d)
        if rec and rec.get("skipped"):
            # 스킵은 중립: 연속을 끊지 않음
            continue
        if rec and rec.get("checked_at"):
            running += 1
            if running > max_streak:
                max_streak = running
        else:
            running = 0

    # 현재 연속(역방향)
    current_streak = 0
    for d in reversed(all_dates):
        # pause면 streak/유효일에서 제외
        if routine_repo.is_paused_for_day(routine, d):
            continue
        if not await is_valid_day(str(user_id), routine.get("weekend_mode", "weekday"), d):
            continue
        rec = rec_map.get(d)
        if rec and rec.get("skipped"):
            # 중립: 계속 뒤로 감
            continue
        if rec and rec.get("checked_at"):
            current_streak += 1
            continue
        break

    return max_streak, current_streak


async def count_paused_days(routine: Dict[str, Any], dates: Optional[List[date]]) -> Tuple[int, List[date]]:
    """주어진 날짜들 중 루틴이 pause 상태인 날짜 수와 날짜 목록을 반환.

    - pause는 통계 분모/스트릭에서 제외되므로, 리포트 투명성(설명용) 지표로만 사용한다.
    """
    if not dates:
        return 0, []

    paused = [d for d in dates if routine_repo.is_paused_for_day(routine, d)]
    return len(paused), paused


async def aggregate_user_metrics(user_id: str, routines: List[Dict[str, Any]], scope: Optional[str], today_local: Optional[date] = None) -> Dict[str, Any]:
    """사용자 전체(루틴별 동등 가중치) 합산 지표를 계산하여 반환.

    개선: all 범위에서도 오늘(today_local)은 제외하고, 루틴 시작일 ~ (today_local - 1) 사이만 집계한다.
    """
    if today_local is None:
        today_local = local_day(now_kst())

    results = []
    total_rate = 0.0
    total_done = 0
    total_valid = 0
    total_paused = 0
    for r in routines:
        # 범위 날짜 리스트 계산
        dates = window_dates(scope, today_local)
        if dates is None:
            # all: 시작일 ~ 어제(today_local - 1)
            start = await _routine_start_date(r, today_local)
            end = today_local - timedelta(days=1)
            # 시작일이 end를 넘어가면 집계할 날짜 없음
            if start > end:
                dates = []
            else:
                dates = await _build_date_range(start, end)

        paused_count, _ = await count_paused_days(r, dates)
        valid_count, valid_days = await count_valid_days(str(user_id), r, dates)
        done_count, _ = await count_done_days(r["id"], valid_days)
        rate = (done_count / max(1, valid_count)) if valid_count > 0 else 0.0
        max_streak, current_streak = await calc_streak(str(user_id), r)

        results.append({
            "id": r["id"],
            "name": r.get("name"),
            "rate": rate,
            "done": done_count,
            "valid": valid_count,
            "paused_days": paused_count,
            "max_streak": max_streak,
            "current_streak": current_streak,
        })

        total_rate += rate
        total_done += done_count
        total_valid += valid_count
        total_paused += paused_count

    avg_rate = (total_rate / len(results)) if results else 0.0

    return {
        "by_routine": results,
        "summary": {
            "avg_rate": avg_rate,
            "total_done": total_done,
            "total_valid": total_valid,
            "total_paused_days": total_paused,
        },
    }
