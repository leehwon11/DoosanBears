"""
두산 베어스 선수 등록 현황 크롤러
- 1군 엔트리 (KBO 공식)
- 2군 엔트리 (KBO 퓨처스)
- 육성선수 (두산 홈페이지)
"""

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from datetime import datetime
import time

BASE_URL = "https://www.koreabaseball.com"
STAFF_POS = {"감독", "코치"}


def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)


def parse_roster_tables(soup, table_class="tNData"):
    """tNData 또는 tbl 클래스 테이블에서 선수 목록 파싱"""
    players = []
    for table in soup.find_all("table", class_=table_class):
        headers = table.find_all("th")
        if not headers:
            continue
        position = headers[1].get_text(strip=True) if len(headers) > 1 else ""
        if position in STAFF_POS:
            continue
        # 유효한 포지션만
        if position not in {"투수", "포수", "내야수", "외야수"}:
            continue

        for row in table.select("tbody tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            link = cells[1].find("a")
            name = link.get_text(strip=True) if link else cells[1].get_text(strip=True)
            href = link.get("href", "") if link else ""
            player_id = href.split("playerId=")[-1] if "playerId=" in href else ""
            if not name:
                continue
            players.append({
                "number":        cells[0].get_text(strip=True),
                "name":          name,
                "position":      position,
                "batting":       cells[2].get_text(strip=True),
                "birth":         cells[3].get_text(strip=True),
                "height_weight": cells[4].get_text(strip=True) if len(cells) > 4 else "",
                "player_id":     player_id,
            })
    return players


def crawl_first_team() -> tuple[list, list, list]:
    """1군 엔트리 + 등록/말소 현황"""
    print("[1군] 크롤링 시작...")
    driver = get_driver()
    try:
        driver.get(f"{BASE_URL}/Player/Register.aspx")
        time.sleep(2)
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "li[data-id='OB'] a"))
        ).click()
        time.sleep(2)
        soup = BeautifulSoup(driver.page_source, "html.parser")
    finally:
        driver.quit()

    roster = parse_roster_tables(soup, "tNData")

    # 등록/말소 파싱
    registered, removed = [], []
    move_h4 = soup.find("h4", class_="bul_history", string=lambda t: t and "등/말소" in t)
    if move_h4:
        for h5 in move_h4.find_all_next("h5", class_="bul_sub"):
            label = h5.get_text(strip=True)
            table = None
            for sib in h5.next_siblings:
                if hasattr(sib, 'name') and sib.name == "table":
                    table = sib
                    break
            if not table:
                continue
            for row in table.select("tbody tr"):
                cells = row.find_all("td")
                if len(cells) < 3:
                    continue
                link = cells[1].find("a")
                name = link.get_text(strip=True) if link else cells[1].get_text(strip=True)
                href = link.get("href", "") if link else ""
                entry = {
                    "number":    cells[0].get_text(strip=True),
                    "name":      name,
                    "position":  cells[2].get_text(strip=True),
                    "player_id": href.split("playerId=")[-1] if "playerId=" in href else "",
                }
                if "말소" in label:
                    removed.append(entry)
                else:
                    registered.append(entry)

    print(f"  1군: {len(roster)}명, 등록: {len(registered)}명, 말소: {len(removed)}명")
    return roster, registered, removed


def crawl_second_team() -> tuple[list, list, list]:
    """2군(퓨처스) 엔트리 + 등록/말소"""
    print("[2군] 크롤링 시작...")
    driver = get_driver()
    try:
        driver.get(f"{BASE_URL}/Futures/Player/Register.aspx")
        time.sleep(2)
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "li[data-id='OB'] a"))
        ).click()
        time.sleep(3)
        soup = BeautifulSoup(driver.page_source, "html.parser")
    finally:
        driver.quit()

    roster = parse_roster_tables(soup, "tbl")

    # 등록/말소 - 마지막 2개 테이블 (헤더: 포지션, 이름, 등번호, 투타유형)
    registered, removed = [], []
    move_tables = [t for t in soup.find_all("table") 
                   if t.find("th") and t.find("th").get_text(strip=True) == "포지션"]
    
    for i, table in enumerate(move_tables):
        for row in table.select("tbody tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            entry = {
                "number":    cells[2].get_text(strip=True) if len(cells) > 2 else "",
                "name":      cells[1].get_text(strip=True),
                "position":  cells[0].get_text(strip=True),
                "player_id": "",
            }
            if i == 0:
                registered.append(entry)
            else:
                removed.append(entry)

    print(f"  2군: {len(roster)}명, 등록: {len(registered)}명, 말소: {len(removed)}명")
    return roster, registered, removed


def crawl_players() -> dict:
    today = datetime.now().strftime("%Y%m%d")
    result = {
        "date": today,
        "crawled_at": datetime.now().isoformat(),
        "roster": [], "registered": [], "removed": [],
        "futures_roster": [], "futures_registered": [], "futures_removed": [],
        "education": [],
    }

    # 1군
    r1, reg1, rem1 = crawl_first_team()
    result["roster"]      = r1
    result["registered"]  = reg1
    result["removed"]     = rem1

    # 2군
    r2, reg2, rem2 = crawl_second_team()
    result["futures_roster"]      = r2
    result["futures_registered"]  = reg2
    result["futures_removed"]     = rem2

    # 요약
    by_pos = {}
    for p in r1:
        by_pos.setdefault(p["position"], []).append(p["name"])
    print("1군 포지션별:")
    for pos, names in by_pos.items():
        print(f"  {pos}: {', '.join(names)}")

    return result


def save_players_to_db(data: dict):
    # players, players_info_backup, players_daily_change 테이블은
    # database.py의 init_db()가 Postgres 스키마로 이미 만들어둠 (여기서 재정의하지 않음)
    from database import get_connection, init_db
    init_db()
    conn = get_connection()

    now = datetime.now().isoformat()
    today = data.get("date") or now[:10]

    # 삭제 전 기존 선수 정보 백업 (전체)
    existing_players = {}
    try:
        rows = conn.execute("SELECT * FROM players").fetchall()
        for r in rows:
            d = dict(r)
            existing_players[d['name']] = d
    except Exception:
        conn.rollback()

    # 1군 선수 정보는 별도 백업 테이블에도 저장 (말소 시 참조용)
    try:
        conn.execute("""
            INSERT INTO players_info_backup
                (name, player_id, number, position, batting, birth, height_weight, status, team_level, updated_at)
            SELECT name, player_id, number, position, batting, birth, height_weight, status, team_level, updated_at
            FROM players WHERE status='active' AND batting != '' AND birth != ''
        """)
        conn.commit()
        # 백업에서도 existing_players 보완
        backup_rows = conn.execute("SELECT * FROM players_info_backup").fetchall()
        for r in backup_rows:
            d = dict(r)
            if d['name'] not in existing_players or not existing_players[d['name']].get('batting'):
                existing_players[d['name']] = d
    except Exception as e:
        print(f"백업(1차) 저장 실패: {e}")
        conn.rollback()

    # 당일 등록/말소 별도 저장 (players_daily_change: date, change_type, player_name, detail, created_at)
    try:
        conn.execute("DELETE FROM players_daily_change WHERE date=?", (today,))
        for p in data.get("registered", []):
            detail = f"{p.get('number','')}번 {p.get('position','')} (1군)"
            conn.execute(
                "INSERT INTO players_daily_change (date, change_type, player_name, detail, created_at) VALUES (?,'registered',?,?,?)",
                (today, p["name"], detail, now)
            )
        for p in data.get("removed", []):
            detail = f"{p.get('number','')}번 {p.get('position','')} (1군)"
            conn.execute(
                "INSERT INTO players_daily_change (date, change_type, player_name, detail, created_at) VALUES (?,'removed',?,?,?)",
                (today, p["name"], detail, now)
            )
        for p in data.get("futures_registered", []):
            detail = f"{p.get('number','')}번 {p.get('position','')} (2군)"
            conn.execute(
                "INSERT INTO players_daily_change (date, change_type, player_name, detail, created_at) VALUES (?,'registered',?,?,?)",
                (today, p["name"], detail, now)
            )
        for p in data.get("futures_removed", []):
            detail = f"{p.get('number','')}번 {p.get('position','')} (2군)"
            conn.execute(
                "INSERT INTO players_daily_change (date, change_type, player_name, detail, created_at) VALUES (?,'removed',?,?,?)",
                (today, p["name"], detail, now)
            )
        conn.commit()
    except Exception as e:
        print(f"당일 변동 저장 실패: {e}")
        conn.rollback()

    # 선수 정보 백업 테이블 업데이트 (2차 - batting/birth 있는 모든 선수)
    try:
        conn.execute("""
            INSERT INTO players_info_backup
                (name, player_id, number, position, batting, birth, height_weight, status, team_level, updated_at)
            SELECT name, player_id, number, position, batting, birth, height_weight, status, team_level, updated_at
            FROM players WHERE batting != '' AND birth != ''
        """)
        conn.commit()
        # 백업에서 existing_players 보완
        backup_rows = conn.execute("SELECT * FROM players_info_backup").fetchall()
        for r in backup_rows:
            d = dict(r)
            if d['name'] not in existing_players or not existing_players[d['name']].get('batting'):
                existing_players[d['name']] = d
    except Exception as e:
        print(f"백업(2차) 저장 실패: {e}")
        conn.rollback()

    conn.execute("DELETE FROM players")

    # 같은 선수가 1군/2군 목록에 동시에 잡히는 날(콜업·말소 당일)이 있어
    # player_id UNIQUE 제약 위반으로 저장 전체가 롤백되던 문제 → 선수당 한 번만 저장 (1군 우선)
    saved_ids, saved_names = set(), set()

    def insert_player(player_id, number, name, position, batting, birth, height_weight, team_level):
        player_id = player_id or None  # 빈 문자열은 UNIQUE 제약과 충돌하지 않도록 NULL로 저장
        if name in saved_names or (player_id and player_id in saved_ids):
            return
        conn.execute("""
            INSERT INTO players (player_id, number, name, position, batting, birth, height_weight, status, team_level, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """, (player_id, number, name, position, batting, birth, height_weight, team_level, now))
        saved_names.add(name)
        if player_id:
            saved_ids.add(player_id)

    # 1군
    for p in data.get("roster", []):
        insert_player(p.get("player_id"), p["number"], p["name"], p["position"],
                      p["batting"], p["birth"], p["height_weight"], '1군')

    # 2군 전체 선수 정보 맵 (이름 기준으로 상세 정보 조회용)
    futures_info = {p["name"]: p for p in data.get("futures_roster", [])}
    # 1군 roster도 맵으로
    roster_info  = {p["name"]: p for p in data.get("roster", [])}

    # 1군 말소 = 2군으로 내려간 선수 → 2군 active로 저장
    # 2군 엔트리 > 1군 roster > 기존 DB 순서로 정보 매칭
    for p in data.get("removed", []):
        info = futures_info.get(p["name"]) or roster_info.get(p["name"])
        if not info:
            # 삭제 전 백업에서 정보 가져오기
            info = existing_players.get(p["name"])
        if not info:
            info = p
        insert_player(info.get("player_id") or p.get("player_id"), p["number"], p["name"], p["position"],
                      info.get("batting", ""), info.get("birth", ""), info.get("height_weight", ""), '2군')

    # 2군 정규 엔트리 (이미 저장된 선수는 insert_player에서 제외)
    for p in data.get("futures_roster", []):
        insert_player(p.get("player_id"), p["number"], p["name"], p["position"],
                      p["batting"], p["birth"], p["height_weight"], '2군')

    # 2군 말소 = 1군으로 올라간 선수 → 이미 1군 roster에 있으므로 스킵
    # (futures_removed는 무시)

    conn.commit()
    conn.close()
    print(f"DB 저장: 1군 {len(data['roster'])}명, 2군 {len(data['futures_roster'])}명")


if __name__ == "__main__":
    data = crawl_players()
    save_players_to_db(data)
    print("\n완료!")
