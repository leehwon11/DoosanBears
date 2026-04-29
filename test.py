import sqlite3
conn = sqlite3.connect('doosan.db')
rows = conn.execute("SELECT team, inning, score FROM inning_scores WHERE game_id='20260428SSOB0' ORDER BY team, inning").fetchall()
for r in rows:
    print(r)
conn.close()