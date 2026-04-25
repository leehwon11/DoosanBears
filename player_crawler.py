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

    # 육성선수 - KBO 퓨처스 육성선수 등록 현황
    print("[육성] 크롤링 시작...")
    edu_roster = []
    try:
        driver3 = get_driver()
        driver3.get("https://www.koreabaseball.com/Futures/Player/Education.aspx")
        time.sleep(2)
        try:
            WebDriverWait(driver3, 8).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "li[data-id='OB'] a"))
            ).click()
            time.sleep(3)
        except:
            pass
        soup3 = BeautifulSoup(driver3.page_source, "html.parser")
        driver3.quit()

        # tNData 또는 tbl 테이블에서 파싱
        for table in soup3.find_all("table"):
            headers = table.find_all("th")
            if not headers:
                continue
            position = headers[1].get_text(strip=True) if len(headers) > 1 else ""
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
                edu_roster.append({
                    "number":        cells[0].get_text(strip=True),
                    "name":          name,
                    "position":      position,
                    "batting":       cells[2].get_text(strip=True),
                    "birth":         cells[3].get_text(strip=True),
                    "height_weight": cells[4].get_text(strip=True) if len(cells) > 4 else "",
                    "player_id":     player_id,
                })
        print(f"  육성: {len(edu_roster)}명")
    except Exception as e:
        print(f"  육성 수집 실패: {e}")

    result["education"] = edu_roster

    # 요약
    by_pos = {}
    for p in r1:
        by_pos.setdefault(p["position"], []).append(p["name"])
    print("1군 포지션별:")
    for pos, names in by_pos.items():
        print(f"  {pos}: {', '.join(names)}")

    return result


def save_players_to_db(data: dict):
    from database import get_connection, init_db
    init_db()
    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id      TEXT,
            number         TEXT,
            name           TEXT NOT NULL,
            position       TEXT,
            batting        TEXT,
            birth          TEXT,
            height_weight  TEXT,
            status         TEXT DEFAULT 'active',
            team_level     TEXT DEFAULT '1군',
            updated_at     TEXT NOT NULL
        )
    """)
    conn.commit()

    now = datetime.now().isoformat()
    conn.execute("DELETE FROM players")

    # 1군
    for p in data.get("roster", []):
        conn.execute("""
            INSERT INTO players (player_id, number, name, position, batting, birth, height_weight, status, team_level, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', '1군', ?)
        """, (p["player_id"], p["number"], p["name"], p["position"],
              p["batting"], p["birth"], p["height_weight"], now))

    for p in data.get("removed", []):
        conn.execute("""
            INSERT INTO players (player_id, number, name, position, status, team_level, updated_at)
            VALUES (?, ?, ?, ?, 'removed', '1군', ?)
        """, (p["player_id"], p["number"], p["name"], p["position"], now))

    # 2군
    for p in data.get("futures_roster", []):
        conn.execute("""
            INSERT INTO players (player_id, number, name, position, batting, birth, height_weight, status, team_level, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', '2군', ?)
        """, (p["player_id"], p["number"], p["name"], p["position"],
              p["batting"], p["birth"], p["height_weight"], now))

    for p in data.get("futures_removed", []):
        conn.execute("""
            INSERT INTO players (player_id, number, name, position, status, team_level, updated_at)
            VALUES (?, ?, ?, ?, 'removed', '2군', ?)
        """, (p["player_id"], p["number"], p["name"], p["position"], now))

    for p in data.get("education", []):
        conn.execute("""
            INSERT INTO players (player_id, number, name, position, batting, birth, height_weight, status, team_level, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', '육성', ?)
        """, (p.get("player_id",""), p["number"], p["name"], p["position"],
              p.get("batting",""), p.get("birth",""), p.get("height_weight",""), now))

    conn.commit()
    conn.close()
    print(f"DB 저장: 1군 {len(data['roster'])}명, 2군 {len(data['futures_roster'])}명, 육성 {len(data.get('education',[]))}명")


if __name__ == "__main__":
    data = crawl_players()
    save_players_to_db(data)
    print("\n완료!")
