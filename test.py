import sqlite3
conn = sqlite3.connect('doosan.db')
conn.execute("""
    DELETE FROM inning_scores WHERE id NOT IN (
        SELECT MIN(id) FROM inning_scores GROUP BY game_id, team, inning
    )
""")
conn.commit()
print("정리 완료:", conn.execute("SELECT COUNT(*) FROM inning_scores").fetchone())
conn.close()