import sqlite3
conn = sqlite3.connect('doosan.db')
try:
    conn.execute('ALTER TABLE games ADD COLUMN stadium TEXT')
    conn.commit()
    print('stadium 컬럼 추가됨')
except:
    print('이미 있음')
conn.close()