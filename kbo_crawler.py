"""
KBO 두산 베어스 경기 결과 크롤러 (최종 완성본)
===============================================
API 구조:
  GetScheduleList    : 경기 ID / 팀 / 점수 / 상태
  GetScoreBoardScroll: 이닝별 점수 + R/H/E
  GetBoxScoreScroll  : 타자(arrHitter) + 투수(arrPitcher)

설치:
    pip install requests beautifulsoup4
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
import json, time, re

BASE_URL = "https://www.koreabaseball.com"
DOOSAN_TEAM_CODE = "OB"


# ──────────────────────────────────────────
# 세션 관리
# ──────────────────────────────────────────

def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9",
    })
    try:
        session.get(f"{BASE_URL}/Default.aspx", timeout=15)
    except Exception as e:
        print(f"    세션 획득 실패: {e}")
    return session


def _ajax_headers(referer: str) -> dict:
    return {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer,
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }


# ──────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────

def _cell(row_arr, idx):
    try:
        return row_arr[idx].get("Text", "") or ""
    except (IndexError, AttributeError):
        return ""

def _gt(row_arr, idx):
    return BeautifulSoup(_cell(row_arr, idx), "html.parser").get_text(strip=True)

def _iv(row_arr, idx):
    try: return int(_gt(row_arr, idx))
    except: return 0

def _fv(row_arr, idx):
    try: return float(_gt(row_arr, idx))
    except: return 0.0

# 포지션 약자 → 전체 이름 변환
POS_MAP = {
    "투": "투수", "포": "포수",
    "一": "1루수", "二": "2루수", "三": "3루수",
    "유": "유격수", "좌": "좌익수", "중": "중견수", "우": "우익수",
    "지": "지명타자", "타": "대타", "주": "대주자",
    "주一": "대주자(1루)", "주二": "대주자(2루)", "주三": "대주자(3루)",
    "타一": "대타→1루수", "타二": "대타→2루수", "타三": "대타→3루수",
    "타유": "대타→유격수", "타좌": "대타→좌익수", "타중": "대타→중견수",
    "타우": "대타→우익수", "타포": "대타→포수", "타지": "대타→지명타자",
    "타투": "대타→투수",
}

def _convert_pos(pos: str) -> str:
    return POS_MAP.get(pos, pos)


def _parse_play_text(play_text):
    soup = BeautifulSoup(play_text, "html.parser")
    spans = [s.get_text(strip=True) for s in soup.find_all("span") if not s.get("class")]
    teams = [s for s in spans if s and s != "vs"]
    em = soup.find("em")
    scores = []
    if em:
        for s in em.find_all("span"):
            try: scores.append(int(s.get_text(strip=True)))
            except ValueError: pass
    home = teams[0] if teams else ""
    away = teams[1] if len(teams) > 1 else ""
    return home, away, scores[0] if scores else 0, scores[1] if len(scores) > 1 else 0

def _extract_game_id(text):
    m = re.search(r'gameId=([^&\'"]+)', text)
    return m.group(1) if m else ""

def _is_finished(row_arr):
    c3, c4 = _cell(row_arr, 3), _cell(row_arr, 4)
    return ("리뷰" in c3 and "프리뷰" not in c3) or ("리뷰" in c4 and "프리뷰" not in c4)


# ──────────────────────────────────────────
# 1단계: 경기 ID 찾기
# ──────────────────────────────────────────

def get_today_game_id(date: str = None, session: requests.Session = None) -> dict | None:
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    if session is None:
        session = _make_session()

    year, month, day = date[:4], date[4:6], date[6:8]
    url = f"{BASE_URL}/ws/Schedule.asmx/GetScheduleList"
    payload = {"leId":"1","srIdList":"0,9,6","seasonId":year,"gameMonth":month,"teamId":DOOSAN_TEAM_CODE}

    print(f"[1] 경기 일정 조회 중... ({date})")
    try:
        resp = session.post(url, headers=_ajax_headers(f"{BASE_URL}/Schedule/Schedule.aspx"), data=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"    오류: {e}")
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

        # 스코어보드 API로 홈/원정 정확히 보정
        try:
            score_data = get_score_board(game_id, session)
            if score_data.get("home_team"):
                home = score_data["home_team"]
                away = score_data["away_team"]
                total = score_data.get("total", {})
                home_score = total.get("home", {}).get("R", home_score)
                away_score = total.get("away", {}).get("R", away_score)
        except:
            pass

        print(f"    발견: {game_id}, {away} {away_score}:{home_score} {home}, 상태={status}")
        return {
            "game_id": game_id, "date": date,
            "home_nm": home, "away_nm": away,
            "home_score": home_score, "away_score": away_score,
            "status": status,
        }

    print(f"    두산 경기 없음 ({date})")
    return None


# ──────────────────────────────────────────
# 2단계: 스코어보드
# ──────────────────────────────────────────

def get_score_board(game_id: str, session: requests.Session) -> dict:
    url = f"{BASE_URL}/ws/Schedule.asmx/GetScoreBoardScroll"
    referer = f"{BASE_URL}/Schedule/GameCenter/Main.aspx?gameDate={game_id[:8]}&gameId={game_id}&section=REVIEW"
    payload = {"leId":"1","srId":"0","seasonId":game_id[:4],"gameId":game_id,"gameDate":game_id[:8]}

    print(f"[2] 스코어보드 수집 중...")
    try:
        resp = session.post(url, headers=_ajax_headers(referer), data=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"    오류: {e}")
        return {}

    result = {
        "home_team": data.get("HOME_NM",""),
        "away_team": data.get("AWAY_NM",""),
        "stadium":   data.get("S_NM",""),
        "innings": {"home":[], "away":[]},
        "total":   {"home":{}, "away":{}},
    }

    # table2: 이닝별 점수 rows[0]=원정, rows[1]=홈
    try:
        table2 = json.loads(data["table2"])
        for i, item in enumerate(table2.get("rows",[])[:2]):
            scores = []
            for cell in item.get("row",[]):
                try: scores.append(int(cell.get("Text","")))
                except: pass
            key = "away" if i == 0 else "home"
            result["innings"][key] = scores
    except Exception as e:
        print(f"    이닝 파싱 오류: {e}")

    # table3: R/H/E rows[0]=원정, rows[1]=홈
    try:
        table3 = json.loads(data["table3"])
        for i, item in enumerate(table3.get("rows",[])[:2]):
            cells = [c.get("Text","") for c in item.get("row",[])]
            def pi(s):
                try: return int(s)
                except: return 0
            key = "away" if i == 0 else "home"
            result["total"][key] = {
                "R": pi(cells[0]) if cells else 0,
                "H": pi(cells[1]) if len(cells)>1 else 0,
                "E": pi(cells[2]) if len(cells)>2 else 0,
            }
    except Exception as e:
        print(f"    R/H/E 파싱 오류: {e}")

    away_r = result['total'].get('away',{}).get('R','?')
    home_r = result['total'].get('home',{}).get('R','?')
    print(f"    스코어: {result['away_team']} {away_r} - {home_r} {result['home_team']}")
    return result


# ──────────────────────────────────────────
# 3단계: 타자/투수 기록
# ──────────────────────────────────────────

def get_box_score(game_id: str, session: requests.Session) -> tuple[list, list]:
    url = f"{BASE_URL}/ws/Schedule.asmx/GetBoxScoreScroll"
    referer = f"{BASE_URL}/Schedule/GameCenter/Main.aspx?gameDate={game_id[:8]}&gameId={game_id}&section=REVIEW"
    payload = {"leId":"1","srId":"0","seasonId":game_id[:4],"gameId":game_id,"gameDate":game_id[:8]}

    print(f"[3] 타자/투수 기록 수집 중...")
    try:
        resp = session.post(url, headers=_ajax_headers(referer), data=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"    오류: {e}")
        return [], []

    # game_id 구조: 날짜(8) + 원정팀코드(2) + 홈팀코드(2) + 번호(1)
    # arrHitter[0]=원정팀(초 공격), arrHitter[1]=홈팀(말 공격)
    # game_id: 날짜8자 + 홈팀코드[8:10] + 원정팀코드[10:12]
    # arrHitter[0]=홈팀, arrHitter[1]=원정팀
    # game_id[8:10]=홈팀코드, game_id[10:12]=원정팀코드
    is_home  = game_id[8:10] == "OB"   # 홈팀코드가 OB=두산이면 홈
    team_idx = 0 if is_home else 1      # 홈이면 [0](홈팀), 원정이면 [1](원정팀)

    # ── 타자 파싱 ──
    batters = []
    try:
        hitter_data = data["arrHitter"][team_idx]
        table1_rows = json.loads(hitter_data["table1"]).get("rows", [])  # 이름/포지션
        table2_rows = json.loads(hitter_data["table2"]).get("rows", [])  # 타석별 결과
        table3_rows = json.loads(hitter_data["table3"]).get("rows", [])  # 타수/안타/타점/볼넷/타율

        for i, (r1, r3) in enumerate(zip(table1_rows, table3_rows)):
            row1 = r1.get("row", [])
            row3 = r3.get("row", [])

            name = _gt(row1, 2)
            if not name or name in ("합계","선수명"):
                continue

            # 타순: row1[0] (1~9, 대타/대주자는 공백일 수 있음)
            order_raw = _gt(row1, 0)
            try:
                batting_order = int(order_raw)
            except ValueError:
                batting_order = 0  # 대타/대주자는 타순 없음

            # table2에서 2루타/3루타/홈런/삼진 카운트
            hr_count = doubles = triples = so_count = 0
            if i < len(table2_rows):
                row2 = table2_rows[i].get("row", [])
                for cell in row2:
                    raw = BeautifulSoup(cell.get("Text", ""), "html.parser").get_text(strip=True)
                    if not raw:
                        continue
                    # "4구/ 우2", "우홈/ 좌2" 처럼 /로 구분된 복합 표기 처리
                    parts = [p.strip() for p in raw.split("/")]
                    for t in parts:
                        if not t:
                            continue
                        if "홈" in t:
                            hr_count += 1
                        elif "삼진" in t:
                            so_count += 1
                        elif (t.endswith("2") or t.endswith("2루")) and not t.startswith("4구"):
                            doubles += 1
                        elif t.endswith("3") or t == "3안":
                            triples += 1

            batters.append({
                "name":          name,
                "position":      _convert_pos(_gt(row1, 1)),
                "batting_order": batting_order,
                "ab":      _iv(row3, 0),
                "h":       _iv(row3, 1),
                "rbi":     _iv(row3, 2),
                "bb":      _iv(row3, 3),
                "avg":     _gt(row3, 4),
                "hr":      hr_count,
                "doubles": doubles,
                "triples": triples,
                "so":      so_count,
                "r":       0,
            })
    except Exception as e:
        print(f"    타자 파싱 오류: {e}")

    # ── 투수 파싱 ──
    # [0]이름 [1]등판(선발 or 등판 이닝 번호) [2]결과 [3]승 [4]패 [5]세 [6]이닝 [7]타자 [8]투구수
    # [9]타수 [10]피안타 [11]피홈런 [12]4사구 [13]삼진 [14]실점 [15]자책 [16]ERA
    # 선발/불펜 모두 같은 열 구조 (예전엔 불펜만 [14]실점을 자책으로 읽고 투구수/타수/실점이 앞 투수 값으로 남는 버그가 있었음)
    pitchers = []
    try:
        pitcher_data = data["arrPitcher"][team_idx]
        table_rows = json.loads(pitcher_data["table"]).get("rows", [])

        for item in table_rows:
            row = item.get("row", [])
            name = _gt(row, 0)
            if not name or name in ("합계","선수명"):
                continue

            # row[1]: 선발은 "선발", 불펜은 등판 이닝 번호(숫자)
            role_raw = _gt(row, 1)
            role = "불펜" if role_raw.isdigit() or not role_raw else role_raw
            result      = _gt(row, 2)
            ip          = _gt(row, 6)
            bf          = _iv(row, 7)
            pitch_count = _iv(row, 8)
            ab_against  = _iv(row, 9)
            h           = _iv(row, 10)
            hr          = _iv(row, 11)
            bb          = _iv(row, 12)   # 4사구 (볼넷+사구)
            so          = _iv(row, 13)
            r           = _iv(row, 14)   # 실점
            er          = _iv(row, 15)   # 자책
            era         = _gt(row, 16)

            pitchers.append({
                "name":        name,
                "role":        role,
                "result":      result,
                "ip":          ip,
                "bf":          bf,
                "pitch_count": pitch_count,
                "ab_against":  ab_against,
                "h":           h,
                "hr":          hr,
                "bb":          bb,
                "so":          so,
                "r":           r,
                "er":          er,
                "era":         era,
            })
    except Exception as e:
        print(f"    투수 파싱 오류: {e}")

    print(f"    타자: {len(batters)}명, 투수: {len(pitchers)}명")
    return batters, pitchers


# ──────────────────────────────────────────
# 전체 실행
# ──────────────────────────────────────────

def crawl_today_game(date: str = None, save_json: bool = True) -> dict:
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    print("=" * 50)
    print(f" 두산 베어스 경기 크롤링 ({date})")
    print("=" * 50)

    session   = _make_session()
    game_info = get_today_game_id(date, session)
    if not game_info:
        return {}

    game_id = game_info["game_id"]
    time.sleep(1)
    score = get_score_board(game_id, session)
    time.sleep(1)
    batters, pitchers = get_box_score(game_id, session)

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
    away_r = sb.get("total",{}).get("away",{}).get("R","?")
    home_r = sb.get("total",{}).get("home",{}).get("R","?")
    print(f"\n  결과: {sb.get('away_team','?')} {away_r} : {home_r} {sb.get('home_team','?')}")

    batters = data.get("batters", [])
    if batters:
        top = sorted(batters, key=lambda x: x.get("h",0), reverse=True)[:3]
        print("  [타자 TOP3]")
        for b in top:
            print(f"    {b['name']} ({b['position']}) {b['ab']}타 {b['h']}안 {b['rbi']}타점 {b['avg']}")

    pitchers = data.get("pitchers", [])
    if pitchers:
        print("  [투수]")
        for p in pitchers:
            print(f"    {p['name']} ({p['result']}) {p['ip']}이닝 {p['er']}자책 {p['so']}K ERA {p['era']}")


def is_game_finished(date: str = None) -> bool:
    """경기 종료 여부 확인 - 스코어보드 이닝 수로 판단"""
    session   = _make_session()
    game_info = get_today_game_id(date, session)
    if not game_info:
        return False

    # 1차: 상태가 종료가 아니면 바로 False
    if game_info.get("status") != "종료":
        return False

    # 2차: 스코어보드에서 실제 이닝 수 확인 (9이닝 이상이어야 진짜 종료)
    try:
        game_id = game_info.get("game_id")
        score = get_score_board(game_id, session)
        home_innings = score.get("innings", {}).get("home", [])
        away_innings = score.get("innings", {}).get("away", [])
        max_innings = max(len(home_innings), len(away_innings))
        if max_innings < 9:
            print(f"    이닝 수 부족 ({max_innings}이닝) — 미종료로 처리")
            return False
    except Exception as e:
        print(f"    이닝 확인 오류: {e}")
        # 오류 시 상태값만으로 판단
        pass

    return True


def get_next_game() -> dict | None:
    """다음 예정 경기 정보 반환"""
    from datetime import datetime as _dt
    session = _make_session()
    today = _dt.now()

    for month_offset in [0, 1]:
        if month_offset == 0:
            target_month = today.month
            target_year  = today.year
        else:
            target_month = today.month % 12 + 1
            target_year  = today.year + (1 if today.month == 12 else 0)

        try:
            _headers = {
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE_URL}/Schedule/GameList.aspx",
            }
            resp = session.post(
                f"{BASE_URL}/ws/Schedule.asmx/GetScheduleList",
                headers=_headers,
                data={"leId":"1","srIdList":"0,9,6","seasonId":str(target_year),
                      "gameMonth":str(target_month).zfill(2),"teamId":DOOSAN_TEAM_CODE},
                timeout=15
            )
            data = resp.json()
        except Exception as e:
            continue

        for item in data.get("rows", []):
            row = item.get("row", [])
            if len(row) < 8:
                continue

            col3 = row[3].get("Text","")
            col4 = row[4].get("Text","")
            is_finished = ("리뷰" in col3 and "프리뷰" not in col3) or ("리뷰" in col4 and "프리뷰" not in col4)

            if is_finished:
                continue

            # 상태 확인
            status = BeautifulSoup(row[8].get("Text",""), "html.parser").get_text(strip=True) if len(row) > 8 else ""
            # 우천취소/더블헤더취소 등 취소 경기 스킵
            if "취소" in status:
                continue

            date_text = BeautifulSoup(row[0].get("Text",""), "html.parser").get_text(strip=True)

            # 오늘 이후 경기만 (오늘 경기는 스케줄러가 처리하므로 내일부터)
            date_clean = date_text[:5].replace(".", "")
            full_date_check = str(target_year) + date_clean
            if full_date_check <= today.strftime("%Y%m%d"):
                continue
            time_text = BeautifulSoup(row[1].get("Text",""), "html.parser").get_text(strip=True)
            play_text = row[2].get("Text","")
            stadium   = BeautifulSoup(row[7].get("Text",""), "html.parser").get_text(strip=True)
            status    = BeautifulSoup(row[8].get("Text",""), "html.parser").get_text(strip=True) if len(row) > 8 else ""

            soup  = BeautifulSoup(play_text, "html.parser")
            teams = [s.get_text(strip=True) for s in soup.find_all("span") if not s.get("class")]
            teams = [t for t in teams if t and t != "vs"]

            if len(teams) < 2:
                continue

            # 날짜 파싱 (MM.DD 형식)
            date_clean = date_text[:5].replace(".", "")  # "04.09" → "0409"
            full_date  = str(target_year) + date_clean   # "20260409"

            # KBO 일정 API: teams[0]=원정팀, teams[1]=홈팀
            away = teams[0]
            home = teams[1]

            return {
                "date":     full_date,
                "date_str": date_text,
                "time":     time_text,
                "home":     home,
                "away":     away,
                "stadium":  stadium,
                "status":   status,
            }
    return None


if __name__ == "__main__":
    data = crawl_today_game()
