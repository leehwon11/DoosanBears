"""
두산 베어스 퓨처스리그 경기 크롤러
=====================================
1군 크롤러(kbo_crawler.py)와 동일한 구조, leId=2
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
import json, time, re

BASE_URL = "https://www.koreabaseball.com"
DOOSAN_TEAM_CODE = "OB"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": f"{BASE_URL}/Futures/Schedule/GameList.aspx",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


def _make_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9",
    })
    try:
        session.get(f"{BASE_URL}/Default.aspx", timeout=15)
    except:
        pass
    return session


def _cell(row_arr, idx):
    try: return row_arr[idx].get("Text", "") or ""
    except: return ""

def _gt(row_arr, idx):
    return BeautifulSoup(_cell(row_arr, idx), "html.parser").get_text(strip=True)

def _extract_game_id(text):
    m = re.search(r'gameId=([^&\'"]+)', text)
    return m.group(1) if m else ""

def _parse_play_text(play_text):
    soup = BeautifulSoup(play_text, "html.parser")
    spans = [s.get_text(strip=True) for s in soup.find_all("span") if not s.get("class")]
    teams = [s for s in spans if s and s != "vs"]
    em = soup.find("em")
    scores = []
    if em:
        for s in em.find_all("span"):
            try: scores.append(int(s.get_text(strip=True)))
            except: pass
    home = teams[0] if teams else ""
    away = teams[1] if len(teams) > 1 else ""
    return home, away, scores[0] if scores else 0, scores[1] if len(scores) > 1 else 0

def _is_finished(row_arr):
    return "리뷰" in _cell(row_arr, 3) or "리뷰" in _cell(row_arr, 4)


def get_futures_game_id(date: str = None, session=None) -> dict | None:
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    if session is None:
        session = _make_session()

    year, month, day = date[:4], date[4:6], date[6:8]

    try:
        resp = session.post(
            f"{BASE_URL}/ws/Schedule.asmx/GetScheduleList",
            headers=HEADERS,
            data={"leId":"2","srIdList":"0,9,6","seasonId":year,"gameMonth":month,"teamId":DOOSAN_TEAM_CODE},
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"    퓨처스 일정 오류: {e}")
        return None

    target_day = f"{month}.{day}"
    for item in data.get("rows", []):
        row_arr = item.get("row", [])
        if target_day not in _cell(row_arr, 0):
            continue
        game_id = _extract_game_id(_cell(row_arr, 3)) or _extract_game_id(_cell(row_arr, 4))
        if not game_id:
            continue
        home, away, home_score, away_score = _parse_play_text(_cell(row_arr, 2))
        status = "종료" if _is_finished(row_arr) else "미종료"
        return {
            "game_id": game_id, "date": date,
            "home_nm": home, "away_nm": away,
            "home_score": home_score, "away_score": away_score,
            "status": status,
        }
    return None


def get_futures_score_board(game_id: str, session) -> dict:
    try:
        resp = session.post(
            f"{BASE_URL}/ws/Schedule.asmx/GetScoreBoardScroll",
            headers={**HEADERS, "Referer": f"{BASE_URL}/Futures/Schedule/GameCenter/Main.aspx?gameId={game_id}"},
            data={"leId":"2","srId":"0","seasonId":game_id[:4],"gameId":game_id,"gameDate":game_id[:8]},
            timeout=15
        )
        data = resp.json()
    except Exception as e:
        return {}

    result = {
        "home_team": data.get("HOME_NM",""),
        "away_team": data.get("AWAY_NM",""),
        "innings": {"home":[], "away":[]},
        "total":   {"home":{}, "away":{}},
    }
    try:
        table2 = json.loads(data["table2"])
        for i, item in enumerate(table2.get("rows",[])[:2]):
            scores = []
            for cell in item.get("row",[]):
                try: scores.append(int(cell.get("Text","")))
                except: pass
            key = "away" if i == 0 else "home"
            result["innings"][key] = scores
    except: pass

    try:
        table3 = json.loads(data["table3"])
        for i, item in enumerate(table3.get("rows",[])[:2]):
            cells = [c.get("Text","") for c in item.get("row",[])]
            def pi(s):
                try: return int(s)
                except: return 0
            key = "away" if i == 0 else "home"
            result["total"][key] = {"R":pi(cells[0]),"H":pi(cells[1]) if len(cells)>1 else 0,"E":pi(cells[2]) if len(cells)>2 else 0}
    except: pass

    return result


def get_futures_box_score(game_id: str, session) -> tuple[list, list]:
    try:
        resp = session.post(
            f"{BASE_URL}/ws/Schedule.asmx/GetBoxScoreScroll",
            headers={**HEADERS, "Referer": f"{BASE_URL}/Futures/Schedule/GameCenter/Main.aspx?gameId={game_id}"},
            data={"leId":"2","srId":"0","seasonId":game_id[:4],"gameId":game_id,"gameDate":game_id[:8]},
            timeout=15
        )
        data = resp.json()
    except Exception as e:
        return [], []

    is_home  = game_id[8:10] == "OB"
    team_idx = 0 if is_home else 1

    batters = []
    try:
        hitter_data = data["arrHitter"][team_idx]
        table1_rows = json.loads(hitter_data["table1"]).get("rows", [])
        table3_rows = json.loads(hitter_data["table3"]).get("rows", [])
        for r1, r3 in zip(table1_rows, table3_rows):
            row1, row3 = r1.get("row",[]), r3.get("row",[])
            def gt1(i): return BeautifulSoup(_cell(row1,i),"html.parser").get_text(strip=True)
            def gt3(i): return BeautifulSoup(_cell(row3,i),"html.parser").get_text(strip=True)
            def iv3(i):
                try: return int(gt3(i))
                except: return 0
            name = gt1(2)
            if not name or name in ("합계","선수명"): continue
            try: order = int(gt1(0))
            except: order = 0
            batters.append({"name":name,"position":gt1(1),"batting_order":order,
                "ab":iv3(0),"h":iv3(1),"rbi":iv3(2),"bb":iv3(3),"avg":gt3(4),"hr":0,"r":0,"so":0})
    except: pass

    pitchers = []
    try:
        pitcher_data = data["arrPitcher"][team_idx]
        table_rows = json.loads(pitcher_data["table"]).get("rows",[])
        for item in table_rows:
            row = item.get("row",[])
            def gt(i): return BeautifulSoup(_cell(row,i),"html.parser").get_text(strip=True)
            def iv(i):
                try: return int(gt(i))
                except: return 0
            name = gt(0)
            if not name or name in ("합계","선수명"): continue
            pitchers.append({"name":name,"role":gt(1),"result":gt(2),"ip":gt(6),
                "bf":iv(7),"h":iv(10),"hr":iv(11),"bb":iv(12),"so":iv(13),"er":iv(15),"era":gt(16)})  # [14]실점 [15]자책
    except: pass

    return batters, pitchers


def crawl_futures_game(date: str = None, save_json: bool = False) -> dict:
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    print(f"[퓨처스] 크롤링 ({date})")
    session   = _make_session()
    game_info = get_futures_game_id(date, session)
    if not game_info:
        print(f"  퓨처스 경기 없음 ({date})")
        return {}

    game_id = game_info["game_id"]
    time.sleep(1)
    score = get_futures_score_board(game_id, session)
    time.sleep(1)
    batters, pitchers = get_futures_box_score(game_id, session)

    result = {
        "crawled_at": datetime.now().isoformat(),
        "date": date, "game_info": game_info,
        "score_board": score, "batters": batters, "pitchers": pitchers,
    }
    if save_json:
        with open(f"futures_{date}.json","w",encoding="utf-8") as f:
            json.dump(result,f,ensure_ascii=False,indent=2)
    print(f"  {game_info['away_nm']} {game_info['away_score']}:{game_info['home_score']} {game_info['home_nm']}")
    return result


def is_futures_finished(date: str = None) -> bool:
    game_info = get_futures_game_id(date)
    if not game_info: return False
    return game_info.get("status") == "종료"


if __name__ == "__main__":
    data = crawl_futures_game()
