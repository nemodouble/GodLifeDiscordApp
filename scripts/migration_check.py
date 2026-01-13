"""DB 스키마(마이그레이션) 체크 스크립트.

용도:
- 다른 환경/다른 DB 파일에서 bot을 올리기 전에,
  필요한 테이블이 자동 생성되는지 빠르게 확인.

사용 예(PowerShell):
  $env:DATABASE_PATH='data\\some_other.db'
  python scripts\\migration_check.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from db.db import init_db, connect_db


async def main() -> None:
    await init_db()
    db = await connect_db()
    try:
        cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        rows = await cur.fetchall()
        names = [r["name"] for r in rows]
        print("tables:", names)
        print("has report_season:", "report_season" in names)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())

