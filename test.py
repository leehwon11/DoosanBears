import sqlite3
conn = sqlite3.connect("doosan.db")

# 타자 기록 컬럼 확인
print("batter_stats 컬럼:", [d[0] for d in conn.execute("SELECT * FROM batter_stats LIMIT 1").description])
print("pitcher_stats 컬럼:", [d[0] for d in conn.execute("SELECT * FROM pitcher_stats LIMIT 1").description])

# 곽빈(투수) 기록 있는지
print("\n곽빈 타자기록:", conn.execute("SELECT COUNT(*) FROM batter_stats WHERE name='곽빈'").fetchone())
print("곽빈 투수기록:", conn.execute("SELECT COUNT(*) FROM pitcher_stats WHERE name='곽빈'").fetchone())

# 양석환(타자) 기록
print("양석환 타자기록:", conn.execute("SELECT COUNT(*) FROM batter_stats WHERE name='양석환'").fetchone())
print("양석환 투수기록:", conn.execute("SELECT COUNT(*) FROM pitcher_stats WHERE name='양석환'").fetchone())
conn.close()