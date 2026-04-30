import sys
sys.path.insert(0, '.')
from kbo_crawler import crawl_today_game
from database import init_db, save_game

init_db()
data = crawl_today_game(date="20230401", save_json=False)
print("stadium in score_board:", data.get("score_board", {}).get("stadium"))
save_game(data)

import sqlite3
conn = sqlite3.connect('doosan.db')
r = conn.execute("SELECT game_id, home_team, away_team, stadium FROM games WHERE date='20230401'").fetchone()
print("DB:", r)
conn.close()