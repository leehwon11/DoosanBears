import sqlite3, requests, os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = f"https://{os.getenv('SUPABASE_PROJECT_ID', 'grdukdqfciipooradmds')}.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
if not SUPABASE_KEY:
    raise SystemExit("SUPABASE_SERVICE_KEY가 .env에 없어요. Supabase 대시보드 > Settings > API에서 service_role 키를 재발급받아 .env에 추가하세요.")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=representation",
}

def upload(table, rows):
    if not rows:
        return
    # 100개씩 나눠서 업로드
    for i in range(0, len(rows), 100):
        chunk = rows[i:i+100]
        r = requests.post(f"{SUPABASE_URL}/rest/v1/{table}", headers=HEADERS, json=chunk)
        print(f"{table} {i+len(chunk)}개 업로드: {r.status_code}")

conn = sqlite3.connect("doosan.db")
conn.row_factory = sqlite3.Row

for table in ["games", "inning_scores", "batter_stats", "pitcher_stats",
              "players", "ai_reports", "futures_games",
              "futures_batter_stats", "futures_pitcher_stats"]:
    try:
        rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
        # id 제거 (Supabase에서 자동 생성)
        for row in rows:
            row.pop("id", None)
        upload(table, rows)
    except Exception as e:
        print(f"{table} 오류: {e}")

conn.close()
print("완료!")