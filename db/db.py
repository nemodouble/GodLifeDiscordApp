import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
import aiosqlite

load_dotenv()
DB_PATH = os.getenv('DATABASE_PATH', './data/database.db')

# SQL 스키마 (CREATE TABLE IF NOT EXISTS)
_SCHEMA_SQL = r"""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS user_settings (
  user_id TEXT PRIMARY KEY,
  tz TEXT NOT NULL DEFAULT 'Asia/Seoul',
  reminder_time TEXT NOT NULL DEFAULT '08:00',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS routine (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  weekend_mode TEXT NOT NULL CHECK(weekend_mode IN ('weekday','weekend','all')),
  deadline_time TEXT,
  notes TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
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
  period TEXT NOT NULL CHECK(period IN ('daily','weekly','monthly')),
  target INTEGER NOT NULL,
  current INTEGER NOT NULL DEFAULT 0,
  carry_over INTEGER NOT NULL DEFAULT 0,
  deadline TEXT,
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

