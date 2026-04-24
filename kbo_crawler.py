"""
KBO 두산 베어스 경기 결과 크롤러 (AJAX API 버전)
=================================================
KBO 사이트는 경기 데이터를 AJAX로 불러오는 구조라
HTML 파싱 대신 내부 API를 직접 호출합니다.

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
# 1단계: 오늘 두산 경기 ID 찾기 (AJAX API)
# ──────────────────────────────────────────

def get_today_game_id(date: str = None) -> dict | None:
    """
    KBO AJAX API로 두산 베어스 경기 ID를 찾습니다.
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    year  = date[:4]
    month = date[4:6]

    url = f"{BASE_URL}/ws/Schedule.asmx/GetScheduleList"
    payload = {
        "leId": "1",
        "srIdList": "0,9,6",   # 정규시즌
        "seasonId": year,
        "gameMonth": month,
        "teamId": DOOSAN_TEAM_CODE,
    }

    print(f"[1] 경기 일정 조회 중... ({date})")
    try:
        resp = requests.post(url, headers=HEADERS, data=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"    오류: {e}")
        return None

    rows = data.get("rows", [])
    for row in rows:
        # GAME_DT: "20260424", G_ID: "20260424OBHH02"
        game_dt = str(row.get("GAME_DT", ""))
        if game_dt != date:
            continue

        game_id = row.get("G_ID", "")
        status  = row.get("G_SC_NM", "")  # "종료" / "경기중" / "예정"
        home    = row.get("HOME_NM", "")
        away    = row.get("AWAY_NM", "")

        print(f"    발견: game_id={game_id}, 상태={status}, {away} vs {home}")
        return {
            "game_id":   game_id,
            "date":      date,
            "home_team": row.get("HOME_KEY", ""),
            "away_team": row.get("AWAY_KEY", ""),
            "home_nm":   home,
            "away_nm":   away,
            "status":    status,
        }

    print(f"    두산 경기 없음 ({date})")
    return None


# ──────────────────────────────────────────
# 2단계: 스코어보드 (AJAX API)
# ──────────────────────────────────────────

def get_score_board(game_id: str) -> dict:
    """이닝별 점수 및 최종 R/H/E 수집"""
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
    for row in rows:
        team_type = row.get("TB_SC_NM", "")  # "홈" / "원정"
        team_nm   = row.get("T_NM", "")

        # 이닝별 점수 (INN_1 ~ INN_12)
        inning_scores = []
        for i in range(1, 13):
            val = row.get(f"INN_{i}", "")
            try:
                inning_scores.append(int(val))
            except (ValueError, TypeError):
                if val not in ("", None):
                    inning_scores.append(0)

        rhe = {
            "R": int(row.get("RHE_R", 0) or 0),
            "H": int(row.get("RHE_H", 0) or 0),
            "E": int(row.get("RHE_E", 0) or 0),
        }

        if team_type == "원정":
            result["away_team"] = team_nm
            result["innings"]["away"] = inning_scores
            result["total"]["away"]   = rhe
        else:
            result["home_team"] = team_nm
            result["innings"]["home"] = inning_scores
            result["total"]["home"]   = rhe

    away_r = result['total'].get('away', {}).get('R', '?')
    home_r = result['total'].get('home', {}).get('R', '?')
    print(f"    스코어: {result['away_team']} {away_r} - {home_r} {result['home_team']}")
    return result


# ──────────────────────────────────────────
# 3단계: 타자 기록 (AJAX API)
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
    for row in data.get("rows", []):
        name = row.get("P_NM", "")
        if not name or name in ("합계", "팀"):
            continue

        def iv(key):
            try: return int(row.get(key, 0) or 0)
            except: return 0

        batters.append({
            "name":     name,
            "position": row.get("POS_NM", ""),
            "ab":  iv("AB_CN"),   # 타수
            "h":   iv("HIT_CN"),  # 안타
            "hr":  iv("HR_CN"),   # 홈런
            "rbi": iv("RBI_CN"),  # 타점
            "r":   iv("RUN_CN"),  # 득점
            "bb":  iv("BB_CN"),   # 볼넷
            "so":  iv("KK_CN"),   # 삼진
            "avg": row.get("HRA_RT", ""),
        })

    print(f"    수집된 타자: {len(batters)}명")
    return batters


# ──────────────────────────────────────────
# 4단계: 투수 기록 (AJAX API)
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
    for row in data.get("rows", []):
        name = row.get("P_NM", "")
        if not name:
            continue

        def iv(key):
            try: return int(row.get(key, 0) or 0)
            except: return 0

        pitchers.append({
            "name":   name,
            "result": row.get("W_L_NM", "-"),  # 승/패/홀드/세이브
            "ip":     row.get("INN_DIS", ""),  # 이닝
            "bf":     iv("BF_CN"),
            "h":      iv("HIT_CN"),
            "hr":     iv("HR_CN"),
            "bb":     iv("BB_CN"),
            "so":     iv("KK_CN"),
            "er":     iv("ER_CN"),
            "era":    row.get("ERA_RT", ""),
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
        "crawled_at": datetime.now().isoformat(),
        "date":       date,
        "game_info":  game_info,
        "score_board": score,
        "batters":    batters,
        "pitchers":   pitchers,
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
    sb   = data.get("score_board", {})
    home = sb.get("home_team", "?")
    away = sb.get("away_team", "?")
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
