import requests, json

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
session.get("https://www.koreabaseball.com/Default.aspx", timeout=15)

game_id = "20260405HHOB0"
resp = session.post(
    "https://www.koreabaseball.com/ws/Schedule.asmx/GetBoxScoreScroll",
    headers={
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://www.koreabaseball.com/Schedule/GameCenter/Main.aspx?gameDate=20260405&gameId={game_id}&section=REVIEW",
    },
    data={"leId":"1","srId":"0","seasonId":"2026","gameId":game_id,"gameDate":"20260405"},
    timeout=15
)
data = resp.json()

for i, pitcher in enumerate(data["arrPitcher"]):
    table = json.loads(pitcher["table"])
    first = table["rows"][0]["row"]
    name = first[0]["Text"]
    print(f"arrPitcher[{i}] 첫 번째 선수: {name}")