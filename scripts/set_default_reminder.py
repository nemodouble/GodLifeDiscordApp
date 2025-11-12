"""Set default reminder_time to 23:00 for existing DB rows.

Actions:
 - UPDATE user_settings rows where reminder_time is NULL or '' to '23:00'
 - INSERT user_settings rows for any user_id present in routine but missing in user_settings

Usage:
  python scripts\set_default_reminder.py
"""
import sqlite3
from pathlib import Path
from datetime import datetime

DB = Path(__file__).resolve().parents[1] / 'data' / 'database.db'
print('DB path:', DB)
if not DB.exists():
    print('Database file does not exist')
    raise SystemExit(1)

conn = sqlite3.connect(DB)
cur = conn.cursor()

now = datetime.utcnow().isoformat()

# Update empty/null reminder_time
print('Updating empty/null reminder_time -> 23:00')
cur.execute("UPDATE user_settings SET reminder_time = '23:00' WHERE reminder_time IS NULL OR reminder_time = ''")
print('rows updated:', cur.rowcount)

# Insert user_settings for users present in routine but missing in user_settings
print('Adding missing user_settings from routine...')
cur.execute("SELECT DISTINCT user_id FROM routine")
users = [r[0] for r in cur.fetchall()]
added = 0
for uid in users:
    cur.execute('SELECT 1 FROM user_settings WHERE user_id = ?', (uid,))
    if cur.fetchone() is None:
        cur.execute("INSERT INTO user_settings(user_id, tz, reminder_time, created_at) VALUES(?, ?, ?, ?)", (uid, 'Asia/Seoul', '23:00', now))
        added += 1

print('added:', added)
conn.commit()
conn.close()
print('Done')

