import sqlite3
conn = sqlite3.connect('doosan.db')
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print('테이블 목록:', tables)
conn.close()