"""
KBO 두산 베어스 경기 결과 크롤러 (실제 응답 구조 기반)
=======================================================
KBO API 응답은 row[] 배열 안에 Text 필드로 데이터가 들어있는 구조입니다.

설치:
    pip install requests beautifulsoup4
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
import json
import time
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.koreabaseball.com/Schedule/Schedule.aspx",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

BASE_URL = "https://www.koreabaseball.com"
DOOSAN_TEAM_CODE = "OB"


# ──────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────

def _text(row_arr, idx):
    """row 배열에서 idx번째 Text 값 반환"""
    try:
        return row_arr[idx].get("Text", "") or ""
    except (IndexError, AttributeError):
        return ""


def _extract_game_id(text):
    """href에서 gameId 추출"""
    m = re.search(r'gameId=([^&\'"]+)', text)
    return m.group(1) if m else ""


def _parse_teams_scores(play_text):
    """
    '<span>두산</span><em><span>3</span><span>vs</span><span>13</span></em><span>삼성</span>'
    → {"home": "두산", "away": "삼성", "home_score": 3, "away_score": 13}
    """
    soup = BeautifulSoup(play_text, "html.parser")
    spans = [s.get_text(strip=True) for s in soup.find_all("span") if not s.get("class")]
    teams = [s for s in spans if s and s != "vs"]

    em = soup.find("em")
    scores_raw = [s.get_text(strip=True) for s in em.find_all("span")] if em else []
    scores = []
    for s in scores_raw:
        try:
            scores.append(int(s))
        except ValueError:
            pass

    home = teams[0] if len(teams) > 0 else ""
    away = teams[1] if len(teams) > 1 else ""
    home_score = scores[0] if len(scores) > 0 else 0
    away_score = scores[1] if len(scores) > 1 else 0

    # 종료 여부: 리뷰/하이라이트 버튼 있으면 종료
    return home, away, home_score, away_score


def _is_finished(row_arr):
    """리뷰 버튼 존재 여부로 경기 종료 판단"""
    relay_text = _text(row_arr, 3)
    return "리뷰" in relay_text or "REVIEW" in relay_text


# ──────────────────────────────────────────
# 1단계: 경기 ID 찾기
# ──────────────────────────────────────────

def get_today_game_id(date: str = None) -> dict | None:
    """KBO 일정 API에서 두산 경기 ID를 찾습니다."""
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    year  = date[:4]
    month = date[4:6]
    day   = date[6:8]

    url = f"{BASE_URL}/ws/Schedule.asmx/GetScheduleList"
    payload = {
        "leId":      "1",
        "srIdList":  "0,9,6",
        "seasonId":  year,
        "gameMonth": month,
        "teamId":    DOOSAN_TEAM_CODE,
    }

    print(f"[1] 경기 일정 조회 중... ({date})")
    try:
        resp = requests.post(url, headers=HEADERS, data=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"    오류: {e}")
        return None

    target_day = f"{month}.{day}"  # "04.01"

    for item in data.get("rows", []):
        row_arr = item.get("row", [])

        # row[0]: 날짜 ("04.01(수)")
        date_text = _text(row_arr, 0)
        if target_day not in date_text:
            continue

        # game_id는 row[3] 또는 row[4] href에서 추출
        game_id = _extract_game_id(_text(row_arr, 3)) or \
                  _extract_game_id(_text(row_arr, 4))
        if not game_id:
            continue

        # 팀/점수
        play_text = _text(row_arr, 2)
        home, away, home_score, away_score = _parse_teams_scores(play_text)

        # 종료 여부
        finished = _is_finished(row_arr)
        status = "종료" if finished else "미종료"

        print(f"    발견: game_id={game_id}, {away} {away_score}:{home_score} {home}, 상태={status}")
        return {
            "game_id":    game_id,
            "date":       date,
            "home_team":  "OB" if "두산" in home else game_id[8:10],
            "away_team":  game_id[10:12],
            "home_nm":    home,
            "away_nm":    away,
            "home_score": home_score,
            "away_score": away_score,
            "status":     status,
        }

    print(f"    두산 경기 없음 ({date})")
    return None


# ──────────────────────────────────────────
# 2단계: 스코어보드
# ──────────────────────────────────────────

def get_score_board(game_id: str) -> dict:
    """이닝별 점수 수집"""
    url = f"{BASE_URL}/ws/GameCenter.asmx/GetScoreBoardData"
    payload = {"gameId": game_id}

    print(f"[2] 스코어보드 수집 중...")
    try:
        resp = requests.post(url, headers=HEADERS, data=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"    오류: {e}")
        return {}

    result = {
        "home_team": "", "away_team": "",
        "innings":   {"home": [], "away": []},
        "total":     {"home": {}, "away": {}},
    }

    rows = data.get("rows", [])
    for i, item in enumerate(rows):
        row_arr = item.get("row", [])
        if not row_arr:
            continue

        team_nm = BeautifulSoup(_text(row_arr, 0), "html.parser").get_text(strip=True)

        # 이닝별 점수: row[1] ~ row[-4] (마지막 3개는 R/H/E)
        score_cells = [_text(row_arr, j) for j in range(1, len(row_arr))]
        rhe_raw  = score_cells[-3:]
        inn_raw  = score_cells[:-3]

        def parse_int(s):
            s = BeautifulSoup(s, "html.parser").get_text(strip=True)
            try: return int(s)
            except: return 0

        inning_list = [parse_int(s) for s in inn_raw if s not in ("", None)]
        rhe = {
            "R": parse_int(rhe_raw[0]) if len(rhe_raw) > 0 else 0,
            "H": parse_int(rhe_raw[1]) if len(rhe_raw) > 1 else 0,
            "E": parse_int(rhe_raw[2]) if len(rhe_raw) > 2 else 0,
        }

        if i == 0:
            result["away_team"] = team_nm
            result["innings"]["away"] = inning_list
            result["total"]["away"]   = rhe
        elif i == 1:
            result["home_team"] = team_nm
            result["innings"]["home"] = inning_list
            result["total"]["home"]   = rhe

    away_r = result['total'].get('away', {}).get('R', '?')
    home_r = result['total'].get('home', {}).get('R', '?')
    print(f"    스코어: {result['away_team']} {away_r} - {home_r} {result['home_team']}")
    return result


# ──────────────────────────────────────────
# 3단계: 타자 기록
# ──────────────────────────────────────────

def get_batter_stats(game_id: str) -> list[dict]:
    """두산 타자 기록 수집"""
    url = f"{BASE_URL}/ws/GameCenter.asmx/GetBatterBoxscore"
    payload = {"gameId": game_id, "teamCode": DOOSAN_TEAM_CODE}

    print(f"[3] 타자 기록 수집 중...")
    try:
        resp = requests.post(url, headers=HEADERS, data=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"    오류: {e}")
        return []

    batters = []
    # 컬럼 순서: 선수명, 포지션, 타수, 안타, 2루타, 3루타, 홈런, 타점, 득점, 볼넷, 삼진, 타율
    COL = {"name":0, "pos":1, "ab":2, "h":3, "2b":4, "3b":5,
           "hr":6, "rbi":7, "r":8, "bb":9, "so":10, "avg":11}

    for item in data.get("rows", []):
        row_arr = item.get("row", [])
        if not row_arr:
            continue

        def gt(idx):
            return BeautifulSoup(_text(row_arr, idx), "html.parser").get_text(strip=True)
        def iv(idx):
            try: return int(gt(idx))
            except: return 0

        name = gt(COL["name"])
        if not name or name in ("합계", "팀", "선수명"):
            continue

        batters.append({
            "name":     name,
            "position": gt(COL["pos"]),
            "ab":  iv(COL["ab"]),
            "h":   iv(COL["h"]),
            "hr":  iv(COL["hr"]),
            "rbi": iv(COL["rbi"]),
            "r":   iv(COL["r"]),
            "bb":  iv(COL["bb"]),
            "so":  iv(COL["so"]),
            "avg": gt(COL["avg"]),
        })

    print(f"    수집된 타자: {len(batters)}명")
    return batters


# ──────────────────────────────────────────
# 4단계: 투수 기록
# ──────────────────────────────────────────

def get_pitcher_stats(game_id: str) -> list[dict]:
    """두산 투수 기록 수집"""
    url = f"{BASE_URL}/ws/GameCenter.asmx/GetPitcherBoxscore"
    payload = {"gameId": game_id, "teamCode": DOOSAN_TEAM_CODE}

    print(f"[4] 투수 기록 수집 중...")
    try:
        resp = requests.post(url, headers=HEADERS, data=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"    오류: {e}")
        return []

    pitchers = []
    COL = {"name":0, "result":1, "ip":2, "bf":3, "h":4,
           "hr":5, "bb":6, "so":7, "er":8, "era":9}

    for item in data.get("rows", []):
        row_arr = item.get("row", [])
        if not row_arr:
            continue

        def gt(idx):
            return BeautifulSoup(_text(row_arr, idx), "html.parser").get_text(strip=True)
        def iv(idx):
            try: return int(gt(idx))
            except: return 0

        name = gt(COL["name"])
        if not name or name in ("합계", "선수명"):
            continue

        pitchers.append({
            "name":   name,
            "result": gt(COL["result"]),
            "ip":     gt(COL["ip"]),
            "bf":     iv(COL["bf"]),
            "h":      iv(COL["h"]),
            "hr":     iv(COL["hr"]),
            "bb":     iv(COL["bb"]),
            "so":     iv(COL["so"]),
            "er":     iv(COL["er"]),
            "era":    gt(COL["era"]),
        })

    print(f"    수집된 투수: {len(pitchers)}명")
    return pitchers


# ──────────────────────────────────────────
# 5단계: 전체 실행
# ──────────────────────────────────────────

def crawl_today_game(date: str = None, save_json: bool = True) -> dict:
    """오늘 두산 경기 전체 크롤링"""
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    print("=" * 50)
    print(f" 두산 베어스 경기 크롤링 ({date})")
    print("=" * 50)

    game_info = get_today_game_id(date)
    if not game_info:
        return {}

    game_id = game_info["game_id"]
    if not game_id:
        return {}

    time.sleep(1)
    score    = get_score_board(game_id)
    time.sleep(1)
    batters  = get_batter_stats(game_id)
    time.sleep(1)
    pitchers = get_pitcher_stats(game_id)

    result = {
        "crawled_at":  datetime.now().isoformat(),
        "date":        date,
        "game_info":   game_info,
        "score_board": score,
        "batters":     batters,
        "pitchers":    pitchers,
    }

    if save_json:
        filename = f"game_{date}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n저장: {filename}")

    _print_summary(result)
    return result


def _print_summary(data: dict):
    if not data: return
    sb     = data.get("score_board", {})
    home   = sb.get("home_team", "?")
    away   = sb.get("away_team", "?")
    home_r = sb.get("total", {}).get("home", {}).get("R", "?")
    away_r = sb.get("total", {}).get("away", {}).get("R", "?")
    print(f"\n  결과: {away} {away_r} : {home_r} {home}")

    batters = data.get("batters", [])
    if batters:
        top = sorted(batters, key=lambda x: x.get("h", 0), reverse=True)[:3]
        print("  [타자 TOP3]")
        for b in top:
            print(f"    {b['name']} {b['ab']}타 {b['h']}안 {b['hr']}홈 {b['rbi']}타점")

    pitchers = data.get("pitchers", [])
    if pitchers:
        print("  [투수]")
        for p in pitchers:
            print(f"    {p['name']} ({p['result']}) {p['ip']}이닝 {p['er']}자책 {p['so']}K")


def is_game_finished(date: str = None) -> bool:
    """경기 종료 여부 확인 (스케줄러용)"""
    game_info = get_today_game_id(date)
    if not game_info:
        return False
    return game_info.get("status") == "종료"


if __name__ == "__main__":
    data = crawl_today_game()
