import sqlite3
conn = sqlite3.connect('doosan.db')
conn.execute("DELETE FROM inning_scores")
conn.commit()
print("이닝 데이터 초기화 완료")
conn.close()