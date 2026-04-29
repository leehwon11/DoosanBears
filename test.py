import sqlite3
conn = sqlite3.connect('doosan.db')
rows = conn.execute("SELECT game_id, date, home_score, away_score, result FROM games WHERE result='무'").fetchall()
for r in rows:
    print(r)
conn.close()