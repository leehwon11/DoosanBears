import requests, json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.koreabaseball.com/Schedule/Schedule.aspx",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}

resp = requests.post(
    "https://www.koreabaseball.com/ws/Schedule.asmx/GetScheduleList",
    headers=HEADERS,
    data={
        "leId": "1",
        "srIdList": "0,9,6",
        "seasonId": "2026",
        "gameMonth": "04",
        "teamId": "OB",
    },
    timeout=15
)
print("Status:", resp.status_code)
data = resp.json()
rows = data.get("rows", [])
print("rows 개수:", len(rows))
if rows:
    print("첫 번째 row 키 목록:", list(rows[0].keys()))
    print("첫 번째 row 내용:", json.dumps(rows[0], ensure_ascii=False, indent=2))