"""
두산 베어스 선수 등록 현황 크롤러 (Selenium 버전)
===================================
실제 브라우저로 KBO 사이트 접속해서 두산 선수 목록 수집
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
    options.add_argument("--headless")          # 백그라운드 실행
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=ko-KR")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )
    return driver


def crawl_players() -> dict:
    today = datetime.now().strftime("%Y%m%d")
    result = {
        "date": today,
        "crawled_at": datetime.now().isoformat(),
        "roster": [], "registered": [], "removed": [],
    }

    print("[1] 브라우저 시작 중...")
    driver = get_driver()

    try:
        print("[2] KBO 선수 등록 현황 페이지 접속...")
        driver.get(f"{BASE_URL}/Player/Register.aspx")
        time.sleep(2)

        print("[3] 두산 팀 클릭...")
        # 두산(OB) 팀 버튼 클릭
        ob_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "li[data-id='OB'] a"))
        )
        ob_btn.click()
        time.sleep(2)  # AJAX 로딩 대기

        print("[4] 선수 데이터 파싱...")
        soup = BeautifulSoup(driver.page_source, "html.parser")

        # 두산 데이터 확인
        if "두산" not in soup.get_text():
            print("    두산 데이터 없음")
            return result

        print("    두산 데이터 발견!")

        # 1군 엔트리 파싱
        roster_h4 = soup.find("h4", class_="bul_history", string=lambda t: t and "선수등록명단" in t)
        if roster_h4:
            for table in roster_h4.find_all_next("table", class_="tNData"):
                prev_h4 = table.find_previous("h4", class_="bul_history")
                if prev_h4 and "등/말소" in prev_h4.get_text():
                    break

                headers = table.find_all("th")
                if not headers:
                    continue
                position = headers[1].get_text(strip=True) if len(headers) > 1 else ""

                if position in STAFF_POS:
                    continue

                for row in table.select("tbody tr"):
                    cells = row.find_all("td")
                    if len(cells) < 4:
                        continue
                    link = cells[1].find("a")
                    name = link.get_text(strip=True) if link else cells[1].get_text(strip=True)
                    href = link.get("href", "") if link else ""
                    player_id = href.split("playerId=")[-1] if "playerId=" in href else ""

                    result["roster"].append({
                        "number":        cells[0].get_text(strip=True),
                        "name":          name,
                        "position":      position,
                        "batting":       cells[2].get_text(strip=True),
                        "birth":         cells[3].get_text(strip=True),
                        "height_weight": cells[4].get_text(strip=True) if len(cells) > 4 else "",
                        "player_id":     player_id,
                    })

        # 등/말소 현황 파싱
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
                    player_id = href.split("playerId=")[-1] if "playerId=" in href else ""
                    entry = {
                        "number":    cells[0].get_text(strip=True),
                        "name":      name,
                        "position":  cells[2].get_text(strip=True),
                        "player_id": player_id,
                    }
                    if "말소" in label:
                        result["removed"].append(entry)
                    else:
                        result["registered"].append(entry)

    finally:
        driver.quit()

    print(f"    1군 엔트리: {len(result['roster'])}명")
    print(f"    등록: {len(result['registered'])}명, 말소: {len(result['removed'])}명")

    by_pos = {}
    for p in result["roster"]:
        by_pos.setdefault(p["position"], []).append(p["name"])
    for pos, names in by_pos.items():
        print(f"    {pos}: {', '.join(names)}")

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
            updated_at     TEXT NOT NULL
        )
    """)
    conn.commit()

    now = datetime.now().isoformat()
    conn.execute("DELETE FROM players")

    for p in data.get("roster", []):
        conn.execute("""
            INSERT INTO players (player_id, number, name, position, batting, birth, height_weight, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
        """, (p["player_id"], p["number"], p["name"], p["position"],
              p["batting"], p["birth"], p["height_weight"], now))

    for p in data.get("removed", []):
        conn.execute("""
            INSERT INTO players (player_id, number, name, position, status, updated_at)
            VALUES (?, ?, ?, ?, 'removed', ?)
        """, (p["player_id"], p["number"], p["name"], p["position"], now))

    conn.commit()
    conn.close()
    print(f"DB 저장 완료: {len(data['roster'])}명 (1군), {len(data['removed'])}명 (말소)")


if __name__ == "__main__":
    data = crawl_players()
    save_players_to_db(data)
    print("\n완료!")
