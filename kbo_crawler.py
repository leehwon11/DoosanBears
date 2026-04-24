"""
KBO 두산 베어스 경기 결과 크롤러
================================
대상: KBO 공식 사이트 (https://www.koreabaseball.com)
수집: 경기 스코어, 이닝별 기록, 선수별 타격/투구 기록
사용: requests + BeautifulSoup4

설치:
    pip install requests beautifulsoup4
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import json
import time
import re


# ──────────────────────────────────────────
# 설정
# ──────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.koreabaseball.com/",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

DOOSAN_TEAM_CODE = "OB"   # KBO 사이트 두산 팀 코드
BASE_URL = "https://www.koreabaseball.com"


# ──────────────────────────────────────────
# 1단계: 오늘 두산 경기 ID 찾기
# ──────────────────────────────────────────

def get_today_game_id(date: str = None) -> dict | None:
    """
    KBO 일정 페이지에서 두산 베어스의 오늘(혹은 지정일) 경기 ID를 찾습니다.

    Args:
        date: "YYYYMMDD" 형식. None이면 오늘 날짜 사용.

    Returns:
        {"game_id": "...", "home": "...", "away": "...", "status": "종료"} 또는 None
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    year  = date[:4]
    month = date[4:6]
    day   = date[6:8]

    url = f"{BASE_URL}/Schedule/Schedule.aspx"
    params = {
        "leagueId": "KBO",
        "seriesId": "0",       # 0 = 정규시즌
        "year": year,
        "month": month,
    }

    print(f"[1] 경기 일정 조회 중... ({date})")
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    오류: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # KBO 일정 테이블에서 해당 날짜·두산 경기 찾기
    # 실제 HTML 구조: <td class="day">일자</td> 안에 <a href="...gmkey=..."> 형태
    for game_link in soup.select("a[href*='gmkey']"):
        href = game_link.get("href", "")

        # gmkey 예: 20260424OBHH02  (날짜+홈팀코드+원정팀코드+번호)
        gmkey_match = re.search(r"gmkey=(\d{8}[A-Z]{4}\d{2})", href)
        if not gmkey_match:
            continue

        gmkey = gmkey_match.group(1)

        # 날짜·두산 포함 여부 확인
        if gmkey[:8] != date:
            continue
        if DOOSAN_TEAM_CODE not in gmkey:
            continue

        # 팀 이름 파싱 (링크 텍스트 or 부모 셀)
        parent_td = game_link.find_parent("td")
        teams_text = parent_td.get_text(" ", strip=True) if parent_td else ""

        # 경기 상태 (종료 / 경기중 / 예정)
        status_tag = soup.select_one(f"[data-gmkey='{gmkey}'] .status")
        status = status_tag.get_text(strip=True) if status_tag else "알수없음"

        print(f"    발견: gmkey={gmkey}, 상태={status}")
        return {
            "game_id": gmkey,
            "date": date,
            "home_team": gmkey[8:10],
            "away_team": gmkey[10:12],
            "status": status,
        }

    print(f"    두산 경기 없음 ({date})")
    return None


# ──────────────────────────────────────────
# 2단계: 경기 스코어 & 이닝별 기록 수집
# ──────────────────────────────────────────

def get_score_board(game_id: str) -> dict:
    """
    경기 스코어보드(이닝별 점수, 최종 R/H/E)를 수집합니다.

    Returns:
        {
            "home_team": "두산",
            "away_team": "한화",
            "innings": {"home": [0,0,3,...], "away": [1,0,0,...]},
            "total":   {"home": {"R":3,"H":8,"E":0}, "away": {...}}
        }
    """
    url = f"{BASE_URL}/Schedule/GameCenter/Main.aspx"
    params = {"gmkey": game_id, "section": "SCORE"}

    print(f"[2] 스코어보드 수집 중... (game_id={game_id})")
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    오류: {e}")
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")

    result = {
        "home_team": "",
        "away_team": "",
        "innings": {"home": [], "away": []},
        "total":   {"home": {}, "away": {}},
    }

    # ── 이닝 스코어 테이블 파싱 ──
    # KBO 사이트: <table class="tbl-lbox-score"> 구조
    score_table = soup.select_one("table.tbl-lbox-score, table.score-table, #tblScore")
    if not score_table:
        print("    스코어 테이블을 찾지 못했습니다.")
        return result

    rows = score_table.select("tr")
    for i, row in enumerate(rows):
        cells = row.select("td, th")
        if not cells:
            continue

        team_name = cells[0].get_text(strip=True)
        if not team_name:
            continue

        # 이닝별 점수 (두 번째 셀부터, 마지막 3개는 R/H/E)
        scores = [c.get_text(strip=True) for c in cells[1:]]

        # 마지막 3개 = R, H, E
        rhe = scores[-3:] if len(scores) >= 3 else ["0", "0", "0"]
        inning_scores = scores[:-3]

        def parse_score(s):
            try:
                return int(s)
            except ValueError:
                return 0  # "-" 또는 빈 값 처리

        inning_list = [parse_score(s) for s in inning_scores]
        rhe_dict = {
            "R": parse_score(rhe[0]),
            "H": parse_score(rhe[1]),
            "E": parse_score(rhe[2]),
        }

        if i == 0:  # 원정팀 (위쪽 행)
            result["away_team"] = team_name
            result["innings"]["away"] = inning_list
            result["total"]["away"] = rhe_dict
        elif i == 1:  # 홈팀 (아래쪽 행)
            result["home_team"] = team_name
            result["innings"]["home"] = inning_list
            result["total"]["home"] = rhe_dict

    print(f"    스코어: {result['away_team']} {result['total'].get('away',{}).get('R','?')}"
          f" - {result['total'].get('home',{}).get('R','?')} {result['home_team']}")
    return result


# ──────────────────────────────────────────
# 3단계: 타자 기록 수집
# ──────────────────────────────────────────

def get_batter_stats(game_id: str, team: str = "doosan") -> list[dict]:
    """
    두산 타자별 오늘 경기 기록을 수집합니다.

    Returns:
        [
            {
                "name": "양석환",
                "position": "1루수",
                "ab": 4,   # 타수
                "h":  2,   # 안타
                "hr": 1,   # 홈런
                "rbi": 2,  # 타점
                "r":  1,   # 득점
                "bb": 0,   # 볼넷
                "so": 1,   # 삼진
                "avg": ".287"
            },
            ...
        ]
    """
    url = f"{BASE_URL}/Schedule/GameCenter/Batter.aspx"
    params = {"gmkey": game_id, "teamCode": DOOSAN_TEAM_CODE}

    print(f"[3] 타자 기록 수집 중...")
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    오류: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    batters = []

    # KBO 타자 테이블 구조:
    # <table id="tblBatterBox"> 또는 <table class="tbl-type01">
    table = soup.select_one("#tblBatterBox, table.tbl-type01")
    if not table:
        print("    타자 테이블을 찾지 못했습니다.")
        return batters

    # 헤더에서 컬럼 순서 파악
    headers_row = table.select_one("thead tr")
    col_names = []
    if headers_row:
        col_names = [th.get_text(strip=True) for th in headers_row.select("th")]

    # 컬럼 인덱스 매핑 (KBO 사이트 기준)
    col_map = {
        "선수명": "name", "포지션": "position",
        "타수": "ab", "안타": "h", "홈런": "hr",
        "타점": "rbi", "득점": "r",
        "볼넷": "bb", "삼진": "so",
        "타율": "avg", "출루율": "obp", "장타율": "slg",
    }

    for row in table.select("tbody tr"):
        cells = row.select("td")
        if not cells or len(cells) < 5:
            continue

        # 합계 행 제외
        row_text = cells[0].get_text(strip=True)
        if row_text in ("합계", "팀"):
            continue

        batter = {}
        for idx, cell in enumerate(cells):
            if idx < len(col_names):
                kor_name = col_names[idx]
                eng_key  = col_map.get(kor_name, kor_name)
                val = cell.get_text(strip=True)
                # 숫자 변환
                if eng_key in ("ab", "h", "hr", "rbi", "r", "bb", "so"):
                    try:
                        batter[eng_key] = int(val)
                    except ValueError:
                        batter[eng_key] = 0
                else:
                    batter[eng_key] = val

        if batter.get("name"):
            batters.append(batter)

    print(f"    수집된 타자 수: {len(batters)}명")
    return batters


# ──────────────────────────────────────────
# 4단계: 투수 기록 수집
# ──────────────────────────────────────────

def get_pitcher_stats(game_id: str) -> list[dict]:
    """
    두산 투수별 오늘 경기 기록을 수집합니다.

    Returns:
        [
            {
                "name": "곽빈",
                "result": "승",    # 승/패/홀드/세이브/-
                "ip": "7.0",       # 이닝
                "bf": 27,          # 상대 타자 수
                "h":  4,           # 피안타
                "hr": 0,           # 피홈런
                "bb": 2,           # 볼넷
                "so": 8,           # 삼진
                "er": 1,           # 자책점
                "era": "2.45"
            },
            ...
        ]
    """
    url = f"{BASE_URL}/Schedule/GameCenter/Pitcher.aspx"
    params = {"gmkey": game_id, "teamCode": DOOSAN_TEAM_CODE}

    print(f"[4] 투수 기록 수집 중...")
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    오류: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    pitchers = []

    table = soup.select_one("#tblPitcherBox, table.tbl-type01")
    if not table:
        print("    투수 테이블을 찾지 못했습니다.")
        return pitchers

    headers_row = table.select_one("thead tr")
    col_names = []
    if headers_row:
        col_names = [th.get_text(strip=True) for th in headers_row.select("th")]

    col_map = {
        "선수명": "name", "결과": "result",
        "이닝": "ip", "상대타자": "bf",
        "피안타": "h", "피홈런": "hr",
        "4구": "bb", "삼진": "so",
        "자책": "er", "평균자책점": "era",
    }

    for row in table.select("tbody tr"):
        cells = row.select("td")
        if not cells or len(cells) < 5:
            continue

        pitcher = {}
        for idx, cell in enumerate(cells):
            if idx < len(col_names):
                kor_name = col_names[idx]
                eng_key  = col_map.get(kor_name, kor_name)
                val = cell.get_text(strip=True)
                if eng_key in ("bf", "h", "hr", "bb", "so", "er"):
                    try:
                        pitcher[eng_key] = int(val)
                    except ValueError:
                        pitcher[eng_key] = 0
                else:
                    pitcher[eng_key] = val

        if pitcher.get("name"):
            pitchers.append(pitcher)

    print(f"    수집된 투수 수: {len(pitchers)}명")
    return pitchers


# ──────────────────────────────────────────
# 5단계: 전체 실행 & 결과 저장
# ──────────────────────────────────────────

def crawl_today_game(date: str = None, save_json: bool = True) -> dict:
    """
    오늘 두산 경기 데이터를 전부 수집해서 딕셔너리로 반환합니다.
    save_json=True 이면 game_YYYYMMDD.json 파일로도 저장합니다.

    사용 예:
        data = crawl_today_game()
        data = crawl_today_game("20260424")   # 특정 날짜 지정
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    print("=" * 50)
    print(f" 두산 베어스 경기 크롤링 시작 ({date})")
    print("=" * 50)

    # 1) 경기 ID 조회
    game_info = get_today_game_id(date)
    if not game_info:
        print("\n오늘 두산 경기가 없거나 아직 종료되지 않았습니다.")
        return {}

    game_id = game_info["game_id"]

    # 2) 스코어보드
    time.sleep(1)  # 서버 부하 방지
    score = get_score_board(game_id)

    # 3) 타자 기록
    time.sleep(1)
    batters = get_batter_stats(game_id)

    # 4) 투수 기록
    time.sleep(1)
    pitchers = get_pitcher_stats(game_id)

    # 결과 합치기
    result = {
        "crawled_at": datetime.now().isoformat(),
        "date": date,
        "game_info": game_info,
        "score_board": score,
        "batters": batters,
        "pitchers": pitchers,
    }

    # JSON 저장
    if save_json:
        filename = f"game_{date}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n결과 저장 완료: {filename}")

    # 요약 출력
    _print_summary(result)

    return result


def _print_summary(data: dict):
    """수집 결과를 보기 좋게 출력합니다."""
    if not data:
        return

    print("\n" + "=" * 50)
    print(" 경기 요약")
    print("=" * 50)

    sb = data.get("score_board", {})
    home = sb.get("home_team", "?")
    away = sb.get("away_team", "?")
    home_r = sb.get("total", {}).get("home", {}).get("R", "?")
    away_r = sb.get("total", {}).get("away", {}).get("R", "?")

    print(f"  {away} {away_r} : {home_r} {home}")

    # 이닝별 스코어
    home_inn = sb.get("innings", {}).get("home", [])
    away_inn = sb.get("innings", {}).get("away", [])
    if home_inn and away_inn:
        header = "이닝: " + "  ".join(str(i+1) for i in range(len(home_inn)))
        print(f"  {header}")
        print(f"  {away}: " + "  ".join(str(s) for s in away_inn))
        print(f"  {home}: " + "  ".join(str(s) for s in home_inn))

    # 두산 타자 TOP 3 (안타 기준)
    batters = data.get("batters", [])
    if batters:
        top = sorted(batters, key=lambda x: x.get("h", 0), reverse=True)[:3]
        print("\n  [두산 타자 TOP 3 - 안타순]")
        for b in top:
            print(f"    {b.get('name','?')} "
                  f"{b.get('ab','?')}타수 {b.get('h','?')}안타 "
                  f"{b.get('hr','?')}홈런 {b.get('rbi','?')}타점")

    # 두산 투수
    pitchers = data.get("pitchers", [])
    if pitchers:
        print("\n  [두산 투수]")
        for p in pitchers:
            print(f"    {p.get('name','?')} "
                  f"({p.get('result','?')}) "
                  f"{p.get('ip','?')}이닝 "
                  f"{p.get('er','?')}자책 "
                  f"{p.get('so','?')}K")


# ──────────────────────────────────────────
# 경기 종료 여부 확인 (Step 3 스케줄러용)
# ──────────────────────────────────────────

def is_game_finished(date: str = None) -> bool:
    """
    두산 경기가 종료됐는지 확인합니다.
    스케줄러에서 30분마다 호출하는 함수입니다.
    """
    game_info = get_today_game_id(date)
    if not game_info:
        return False
    return game_info.get("status") == "종료"


# ──────────────────────────────────────────
# 실행
# ──────────────────────────────────────────

if __name__ == "__main__":
    # 오늘 경기 크롤링
    data = crawl_today_game()

    # 특정 날짜 지정하고 싶다면:
    # data = crawl_today_game("20260420")
