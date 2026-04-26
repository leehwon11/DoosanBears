import requests, json
from bs4 import BeautifulSoup

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})
session.get("https://www.koreabaseball.com/Default.aspx", timeout=15)

game_id = "20260424LGOB0"
resp = session.post(
    "https://www.koreabaseball.com/ws/Schedule.asmx/GetBoxScoreScroll",
    headers={
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://www.koreabaseball.com/Schedule/GameCenter/Main.aspx?gameId={game_id}",
    },
    data={"leId":"1","srId":"0","seasonId":"2026","gameId":game_id,"gameDate":"20260424"},
    timeout=15
)
data = resp.json()
pitcher_data = data["arrPitcher"][1]
table_rows = json.loads(pitcher_data["table"]).get("rows", [])
for item in table_rows[:4]:
    row = item.get("row", [])
    print([BeautifulSoup(c.get("Text",""), "html.parser").get_text(strip=True) for c in row[:8]])