import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
import aiosqlite

load_dotenv()
_raw_db = os.getenv('DATABASE_PATH', './data/database.db')

# Ensure DATABASE_PATH is resolved relative to the project root (repo top-level)
# This prevents different callers (with different CWDs) from creating DB files
# in different locations. db.py is located at <project_root>/db/db.py, so
# project_root = parent of the db/ directory.
_project_root = Path(__file__).resolve().parents[1]
if Path(_raw_db).is_absolute():
    DB_PATH = str(Path(_raw_db))
else:
    DB_PATH = str((_project_root / _raw_db).resolve())

# SQL 스키마 (CREATE TABLE IF NOT EXISTS)
_SCHEMA_SQL = r"""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS user_settings (
  user_id TEXT PRIMARY KEY,
  tz TEXT NOT NULL DEFAULT 'Asia/Seoul',
  reminder_time TEXT NOT NULL DEFAULT '23:00',
  created_at TEXT NOT NULL
);

-- (확장) 리포트 시즌(다시 마음먹기)
CREATE TABLE IF NOT EXISTS report_season (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '시즌',
  start_day TEXT NOT NULL,
  end_day TEXT,
  created_at TEXT NOT NULL,
  closed_at TEXT,
  is_active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_report_season_user_start ON report_season(user_id, start_day);

CREATE TABLE IF NOT EXISTS routine (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  weekend_mode TEXT NOT NULL CHECK(weekend_mode IN ('weekday','weekend','all')),
  deadline_time TEXT,
  notes TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  order_index INTEGER
);

CREATE TABLE IF NOT EXISTS routine_checkin (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  routine_id INTEGER NOT NULL,
  user_id TEXT NOT NULL,
  local_day TEXT NOT NULL,
  checked_at TEXT,
  undone_at TEXT,
  skipped INTEGER NOT NULL DEFAULT 0,
  skip_reason TEXT,
  UNIQUE (routine_id, local_day)
);

CREATE TABLE IF NOT EXISTS goal (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  title TEXT NOT NULL,
  deadline TEXT,
  description TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS goal_progress (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  goal_id INTEGER NOT NULL,
  user_id TEXT NOT NULL,
  delta INTEGER NOT NULL,
  value_after INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exemption (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  start_day TEXT NOT NULL,
  end_day TEXT NOT NULL,
  reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_checkin_user_day ON routine_checkin(user_id, local_day);
CREATE INDEX IF NOT EXISTS idx_goal_user ON goal(user_id, active);
"""


async def _ensure_routine_order_index(db: aiosqlite.Connection) -> None:
    """기존 DB에 routine.order_index 컬럼이 없으면 추가하고, NULL 값은 user_id별 id 순서로 초기화."""
    cur = await db.execute("PRAGMA table_info(routine)")
    cols = [r[1] for r in await cur.fetchall()]  # (cid, name, type, notnull, dflt_value, pk)
    await cur.close()

    if "order_index" not in cols:
        await db.execute("ALTER TABLE routine ADD COLUMN order_index INTEGER")

    # NULL 인 값들만 user_id별 id 순서로 채우기
    cur = await db.execute("SELECT id, user_id FROM routine WHERE order_index IS NULL ORDER BY user_id, id")
    rows = await cur.fetchall()
    await cur.close()

    idx_by_user: dict[str, int] = {}
    for rid, uid in rows:
        uid = str(uid)
        idx_by_user[uid] = idx_by_user.get(uid, 0) + 1
        await db.execute("UPDATE routine SET order_index = ? WHERE id = ?", (idx_by_user[uid], rid))


async def _fix_season_start_day_to_first_checkin(db: aiosqlite.Connection) -> None:
    """시즌 도입 초기에 '오늘부터 시작'으로 잘못 만들어진 1개짜리 시즌을 과거 체크인 포함으로 보정.

    안전 조건:
    - report_season이 존재
    - 해당 user_id의 시즌 수가 정확히 1개
    - 그 시즌의 start_day가 오늘(서버 기준 date('now'))
    - routine_checkin에 더 이른 first_checkin_day(MIN(local_day), done/skipped=0)가 존재

    이때에만 start_day를 first_checkin_day로 수정한다.
    """
    # 보고서 시즌 테이블이 아예 없는 DB면 스킵
    cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='report_season'")
    has = await cur.fetchone()
    await cur.close()
    if not has:
        return

    # user별 조건에 맞는 시즌을 찾아 업데이트
    cur = await db.execute(
        """
        SELECT rs.user_id, rs.id AS season_id,
               rs.start_day,
               (
                 SELECT MIN(local_day)
                 FROM routine_checkin rc
                 WHERE rc.user_id = rs.user_id AND rc.checked_at IS NOT NULL AND rc.skipped = 0
               ) AS first_day,
               (
                 SELECT COUNT(1)
                 FROM report_season r2
                 WHERE r2.user_id = rs.user_id
               ) AS season_cnt
        FROM report_season rs
        WHERE rs.start_day = date('now')
        """
    )
    rows = await cur.fetchall()
    await cur.close()

    for r in rows:
        user_id = r[0]
        season_id = r[1]
        first_day = r[3]
        season_cnt = r[4]

        if season_cnt != 1:
            continue
        if not first_day:
            continue
        # first_day가 오늘보다 이전일 때만 보정
        try:
            if str(first_day) >= str(r[2]):
                continue
        except Exception:
            # 문자열 비교 실패 시에도 안전하게 스킵
            continue

        await db.execute(
            "UPDATE report_season SET start_day = ? WHERE id = ? AND user_id = ?",
            (str(first_day), int(season_id), str(user_id)),
        )


async def init_db(db_path: str | None = None) -> None:
    """Ensure DB file & directory exist and create tables/indexes if missing.

    사용 예:
      await init_db()
    또는
      asyncio.run(init_db())
    """
    path = db_path or DB_PATH
    # Ensure directory exists
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(path) as db:
        # Use WAL for better concurrency in future
        await db.execute("PRAGMA journal_mode = WAL;")
        # Execute schema
        await db.executescript(_SCHEMA_SQL)

        # 자동 마이그레이션(기존 DB 보정)
        await _ensure_routine_order_index(db)
        await _fix_season_start_day_to_first_checkin(db)

        await db.commit()


async def connect_db(db_path: str | None = None) -> aiosqlite.Connection:
    """Return an aiosqlite connection with useful defaults.

    사용 예:
      async with await connect_db() as db:
          await db.execute(...)  # 또는 fetch 등
    """
    path = db_path or DB_PATH
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON;")
    return conn


if __name__ == '__main__':
    # 간단한 실행: init DB
    asyncio.run(init_db())
    print(f'Initialized database at: {DB_PATH}')
