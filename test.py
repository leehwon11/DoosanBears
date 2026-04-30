import sqlite3
conn = sqlite3.connect('doosan.db')

print("=== batter_stats 컬럼 ===")
cols = [d[1] for d in conn.execute('PRAGMA table_info(batter_stats)').fetchall()]
print(cols)

print("\n=== pitcher_stats 컬럼 ===")
cols = [d[1] for d in conn.execute('PRAGMA table_info(pitcher_stats)').fetchall()]
print(cols)

print("\n=== games 컬럼 ===")
cols = [d[1] for d in conn.execute('PRAGMA table_info(games)').fetchall()]
print(cols)

conn.close()