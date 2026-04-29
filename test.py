import sqlite3
conn = sqlite3.connect('doosan.db')
# players 테이블 전체에서 임종성 확인
rows = conn.execute("SELECT * FROM players WHERE name='임종성' ORDER BY id").fetchall()
for r in rows:
    print(r)
conn.close()