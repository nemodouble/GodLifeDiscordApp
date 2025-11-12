import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / 'data' / 'database.db'
print('DB path:', DB)
if not DB.exists():
    print('Database file does not exist')
    raise SystemExit(1)

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print('\n-- user_settings --')
try:
    cur.execute('SELECT user_id, tz, reminder_time, created_at FROM user_settings')
    rows = cur.fetchall()
    if not rows:
        print('no user_settings rows')
    else:
        for r in rows:
            print(dict(r))
except Exception as e:
    print('error reading user_settings:', e)

print('\n-- routine (sample) --')
try:
    cur.execute('SELECT id, user_id, name, weekend_mode, deadline_time, active FROM routine')
    rows = cur.fetchall()
    if not rows:
        print('no routines')
    else:
        for r in rows:
            print(dict(r))
except Exception as e:
    print('error reading routine:', e)

print('\n-- routine_checkin (sample) --')
try:
    cur.execute('SELECT id, routine_id, user_id, local_day, checked_at, skipped FROM routine_checkin')
    rows = cur.fetchall()
    if not rows:
        print('no routine_checkin rows')
    else:
        for r in rows[:10]:
            print(dict(r))
except Exception as e:
    print('error reading routine_checkin:', e)

conn.close()

