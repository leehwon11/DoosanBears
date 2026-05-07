import requests
from bs4 import BeautifulSoup
import urllib3
urllib3.disable_warnings()

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})

for url in [
    "https://www.doosanbears.com/member/pitchers",
    "https://www.doosanbears.com/member/batters",
    "https://www.doosanbears.com/member/catchers",
]:
    resp = session.get(url, timeout=15, verify=False)
    soup = BeautifulSoup(resp.text, "html.parser")
    print(f"\n{url}")
    print("상태:", resp.status_code)
    # 선수 이름 찾기
    names = soup.select(".player-name, .name, h3, h4, .player_name")
    print("요소 수:", len(names))
    print("텍스트:", [n.get_text(strip=True) for n in names[:5]])