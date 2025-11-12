from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any

from db.db import connect_db
from domain.time_utils import is_valid_day, local_day, now_kst


def window_dates(scope: Optional[str], today_local: date) -> Optional[List[date]]:
    """주어된 범위(scope)에 대한 날짜 리스트를 반환.

    scope: '7d' | '30d' | 'all' 또는 None
    반환값: 날짜 리스트 (최근 포함, 역순 아님). 'all'의 경우 None 반환하여 호출자가 범위를 동적으로 계산하도록 함.
    """
    if scope == "7d":
        return [today_local - timedelta(days=i) for i in range(0, 7)][::-1]
    if scope == "30d":
        return [today_local - timedelta(days=i) for i in range(0, 30)][::-1]
    # all -> None
    return None


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

    - is_valid_day(user_id, weekend_mode, d)가 True여야 함
    - 사용자가 스킵(skipped=1)으로 표시한 날짜는 유효일에서 제외함
    dates가 None이면 루틴 생성일 ~ 오늘 범위를 사용하도록 호출자가 결정해야 함.
    """
    if dates is None:
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
        # is_valid_day는 async
        if not await is_valid_day(str(user_id), routine.get("weekend_mode", "weekday"), d):
            continue
        # 사용자가 스킵으로 표시했으면 유효일에서 제외
        if skipped_map.get(d, False):
            continue
        valid_days.append(d)

    return len(valid_days), valid_days


async def _build_date_range(start: date, end: date) -> List[date]:
    days: List[date] = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur = cur + timedelta(days=1)
    return days


async def calc_streak(user_id: str, routine: Dict[str, Any]) -> Tuple[int, int]:
    """루틴의 유효일 기준 최대 연속 완료(max_streak)와 현재 진행중인 연속 완료(current_streak)를 계산하여 반환.

    알고리즘 요약:
      - 루틴 생성일(created_at)을 시작으로 오늘까지 모든 날짜를 순회
      - 각 날짜에 대해 is_valid_day 검사. 유효하지 않으면 건너뜀(연속성에 영향 없음)
      - 유효한 날짜에 대해 체크인 레코드를 확인: skipped이면 건너뜀(중립), checked이면 완료로 간주(연속 증가), 그렇지 않으면 연속 종료
      - max_streak은 전체 기간 동안의 최대 연속 완료 수
      - current_streak은 가장 최신 유효일(오늘 포함)부터 거꾸로 가며 연속 완료된 날 수
    """
    # 오늘의 local_day
    today = local_day(now_kst())

    # 시작일 결정: 루틴.created_at 우선, 없으면 DB의 가장 오래된 체크인, 또 없으면 365일 전
    start_date: Optional[date] = None
    created_at = routine.get("created_at")
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at)
            start_date = local_day(dt)
        except Exception:
            start_date = None

    if start_date is None:
        # DB에서 earliest local_day 조회
        conn = await connect_db()
        try:
            cur = await conn.execute("SELECT MIN(local_day) as m FROM routine_checkin WHERE routine_id = ?", (routine["id"],))
            row = await cur.fetchone()
            await cur.close()
            if row and row["m"]:
                start_date = datetime.fromisoformat(row["m"]).date()
        finally:
            await conn.close()

    if start_date is None:
        start_date = today - timedelta(days=365)

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
        if not await is_valid_day(str(user_id), routine.get("weekend_mode", "weekday"), d):
            continue
        rec = rec_map.get(d)
        if rec and rec.get("skipped"):
            # 스킵은 중립: 연속을 끊지 않음, 그러나 완료수에는 포함되지 않음
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
        if not await is_valid_day(str(user_id), routine.get("weekend_mode", "weekday"), d):
            continue
        rec = rec_map.get(d)
        if rec and rec.get("skipped"):
            # 중립: 계속 뒤로 감
            continue
        if rec and rec.get("checked_at"):
            current_streak += 1
            continue
        # 유효한 날이면서 완료도 아니고 스킵도 아니면 현재 연속 종료
        break

    return max_streak, current_streak


async def aggregate_user_metrics(user_id: str, routines: List[Dict[str, Any]], scope: Optional[str], today_local: Optional[date] = None) -> Dict[str, Any]:
    """사용자 전체(루틴별 동일 가중치) 합산 지표를 계산하여 반환.

    반환 예시:
      {
        "by_routine": [ {"id": ..., "name": ..., "rate": 0.8, "done": x, "valid": y, "max_streak": a, "current_streak": b }, ... ],
        "summary": {"avg_rate": 0.75, "total_done": N, "total_valid": M}
      }
    """
    if today_local is None:
        today_local = local_day(now_kst())

    results = []
    total_rate = 0.0
    total_done = 0
    total_valid = 0
    for r in routines:
        # 범위 날짜 리스트 계산
        dates = window_dates(scope, today_local)
        if dates is None:
            # all: 생성일~오늘
            created_at = r.get("created_at")
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at)
                    start = local_day(dt)
                except Exception:
                    start = today_local - timedelta(days=365)
            else:
                start = today_local - timedelta(days=365)
            dates = await _build_date_range(start, today_local)

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
            "max_streak": max_streak,
            "current_streak": current_streak,
        })

        total_rate += rate
        total_done += done_count
        total_valid += valid_count

    avg_rate = (total_rate / len(results)) if results else 0.0

    return {"by_routine": results, "summary": {"avg_rate": avg_rate, "total_done": total_done, "total_valid": total_valid}}

