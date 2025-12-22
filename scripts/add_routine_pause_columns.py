import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / 'data' / 'database.db'
print('DB path:', DB)
if not DB.exists():
    print('Database file does not exist')
    raise SystemExit(1)

conn = sqlite3.connect(DB)
cur = conn.cursor()

cur.execute("PRAGMA table_info(routine)")
cols = [r[1] for r in cur.fetchall()]

# paused: 0/1
if 'paused' not in cols:
    print('Adding paused column to routine table...')
    cur.execute("ALTER TABLE routine ADD COLUMN paused INTEGER NOT NULL DEFAULT 0")
    conn.commit()
else:
    print('paused column already exists.')

# paused_until: YYYY-MM-DD (inclusive)
if 'paused_until' not in cols:
    print('Adding paused_until column to routine table...')
    cur.execute("ALTER TABLE routine ADD COLUMN paused_until TEXT")
    conn.commit()
else:
    print('paused_until column already exists.')

print('Done.')
conn.close()

