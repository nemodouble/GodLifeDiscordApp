"""간단한 스크립트: 목표 테이블(goal)만 DROP 후 새 스키마로 CREATE 합니다.
주의: 기존 목표 데이터가 모두 삭제됩니다.
사용법:
  python scripts\recreate_goal_table.py
"""
import asyncio
from db.db import connect_db

_RECREATE_SQL = r"""
DROP TABLE IF EXISTS goal;
CREATE TABLE goal (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  title TEXT NOT NULL,
  deadline TEXT,
  description TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
"""


async def main():
    print("경고: 기존 goal 테이블의 모든 데이터가 삭제됩니다.")
    confirm = input("계속 진행하시겠습니까? (y/N): ")
    if confirm.lower() != 'y':
        print("취소됨")
        return

    conn = await connect_db()
    try:
        await conn.executescript(_RECREATE_SQL)
        await conn.commit()
        print("goal 테이블을 재생성했습니다.")
    finally:
        await conn.close()


if __name__ == '__main__':
    asyncio.run(main())

