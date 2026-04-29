import sqlite3
conn = sqlite3.connect('doosan.db')
row = conn.execute("SELECT * FROM players WHERE name='임종성'").fetchone()
print(row)
conn.close()