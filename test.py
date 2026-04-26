import sqlite3
conn = sqlite3.connect('doosan.db')
rows = conn.execute(
    'SELECT id, game_id, name, batting_order, ab, h FROM batter_stats WHERE game_id=? ORDER BY name, id LIMIT 20',
    ('20260410OBKT0',)
).fetchall()
for r in rows:
    print(r)
conn.close()