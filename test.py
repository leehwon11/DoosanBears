import sqlite3
conn = sqlite3.connect("doosan.db")
print([d[0] for d in conn.execute("SELECT * FROM pitcher_stats LIMIT 1").description])
rows = conn.execute("SELECT name, result FROM pitcher_stats WHERE game_id = '20260405HHOB0'").fetchall()
for r in rows:
    print(r)
conn.close()