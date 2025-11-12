from __future__ import annotations

from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from functools import lru_cache
from typing import Union

import holidays

from db.db import connect_db

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    """현재 시각을 KST(Asia/Seoul)로 반환합니다."""
    return datetime.now(tz=KST)


def local_day(dt: Union[datetime, date]) -> date:
    """
    로컬의 '업무일'을 계산합니다.

    규칙: local_day(dt) = (dt - 4시간).date()
    즉, 날짜 경계가 04:00 KST 입니다.

    입력으로 datetime이나 date를 받습니다. date면 그 날짜의 자정(00:00)을
    KST 기준으로 간주합니다.
    """
    if isinstance(dt, date) and not isinstance(dt, datetime):
        # date만 들어오면 그 날짜의 00:00 KST로 간주
        dt = datetime(dt.year, dt.month, dt.day, tzinfo=KST)
    else:
        # datetime이면 KST로 변환
        if dt.tzinfo is None:
            # naive datetime은 KST로 간주
            dt = dt.replace(tzinfo=KST)
        else:
            dt = dt.astimezone(KST)

    adjusted = dt - timedelta(hours=4)
    return adjusted.date()


def is_weekend(d: Union[date, datetime]) -> bool:
    """날짜가 주말(토/일)인지 확인합니다."""
    if isinstance(d, datetime):
        d = d.date()
    return d.weekday() >= 5  # 5: Saturday, 6: Sunday


@lru_cache(maxsize=10)
def _holiday_set_for_year(year: int) -> set[date]:
    """주어진 연도의 한국 공휴일 집합을 반환합니다. 캐시 사용."""
    # holidays 라이브러리의 CountryHoliday를 사용
    kr = holidays.CountryHoliday("KR", years=year)
    return set(kr.keys())


def is_korean_holiday(d: Union[date, datetime]) -> bool:
    """한국 공휴일인지 확인합니다. 연도별 캐시 사용."""
    if isinstance(d, datetime):
        d = d.date()
    return d in _holiday_set_for_year(d.year)


async def is_exempt(user_id: str, d: Union[date, datetime]) -> bool:
    """DB의 exemption 테이블을 확인해 주어진 날짜에 사용자가 면책인지 확인합니다.

    exemption 테이블의 start_day, end_day 칼럼은 ISO 포맷(YYYY-MM-DD) 문자열로 저장되어 있다고 가정합니다.
    """
    if isinstance(d, datetime):
        d = d.date()
    iso = d.isoformat()
    conn = await connect_db()
    try:
        cur = await conn.execute(
            "SELECT 1 FROM exemption WHERE user_id = ? AND start_day <= ? AND end_day >= ? LIMIT 1",
            (user_id, iso, iso),
        )
        row = await cur.fetchone()
        await cur.close()
        return row is not None
    finally:
        await conn.close()


def is_applicable_day(weekend_mode: str, d: Union[date, datetime]) -> bool:
    """주말 모드에 따라 해당 날짜가 적용 대상인지 확인합니다.

    weekend_mode: 'weekday' | 'weekend' | 'all'
    """
    if isinstance(d, datetime):
        d = d.date()
    m = (weekend_mode or "").lower()
    if m == "all":
        return True
    if m == "weekday":
        return not is_weekend(d)
    if m == "weekend":
        return is_weekend(d)
    raise ValueError(f"Invalid weekend_mode: {weekend_mode}")


async def is_valid_day(user_id: str, weekend_mode: str, d: Union[date, datetime]) -> bool:
    """주말/공휴일/면책을 종합해 '유효한(체크인이 필요한) 날짜'인지 반환합니다.

    정책(기본 해석):
      - 사용자가 면책(exemption)인 경우: 유효하지 않음 (체크인이 필요 없음)
      - weekend_mode에 의해 적용 대상이 아니면 유효하지 않음
      - 공휴일이면 유효하지 않음
      - 위 조건을 모두 통과하면 유효함
    """
    if isinstance(d, datetime):
        d = d.date()
    # 면책 우선
    if await is_exempt(user_id, d):
        return False
    # 주말 모드 검사
    if not is_applicable_day(weekend_mode, d):
        return False
    # 공휴일 검사
    if is_korean_holiday(d):
        return False
    return True


# 간단한 스모크 테스트: 03:59 -> 04:00 경계 확인
if __name__ == "__main__":
    dt1 = datetime(2025, 11, 11, 3, 59, tzinfo=KST)
    dt2 = datetime(2025, 11, 11, 4, 0, tzinfo=KST)
    print("now_kst() =", now_kst())
    print("local_day(2025-11-11 03:59) =", local_day(dt1))
    print("local_day(2025-11-11 04:00) =", local_day(dt2))
    # 기대: dt1은 하루 전일(2025-11-10)로, dt2는 2025-11-11로 구분됨
