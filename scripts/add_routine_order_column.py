import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / 'data' / 'database.db'
print('DB path:', DB)
if not DB.exists():
    print('Database file does not exist')
    raise SystemExit(1)

conn = sqlite3.connect(DB)
cur = conn.cursor()

# 1) routine 테이블에 order_index 컬럼이 없으면 추가
cur.execute("PRAGMA table_info(routine)")
cols = [r[1] for r in cur.fetchall()]

if 'order_index' not in cols:
    print('Adding order_index column to routine table...')
    cur.execute("ALTER TABLE routine ADD COLUMN order_index INTEGER")
    conn.commit()
else:
    print('order_index column already exists.')

# 2) user_id 별로 현재 id 순서대로 기본 order_index 세팅 (NULL 인 행만)
print('Initializing order_index for existing rows (per user by id)...')
cur.execute("SELECT id, user_id FROM routine WHERE order_index IS NULL ORDER BY user_id, id")
rows = cur.fetchall()

from collections import defaultdict
counter = defaultdict(int)

for rid, user_id in rows:
    counter[user_id] += 1
    idx = counter[user_id]
    cur.execute("UPDATE routine SET order_index = ? WHERE id = ?", (idx, rid))

conn.commit()

print('Done. Updated rows:', len(rows))
conn.close()

