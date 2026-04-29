"""
두산 베어스 과거 경기 일괄 크롤링
===================================
사용법:
  python bulk_crawl.py              # 올 시즌 전체 (2026-03-01 ~ 오늘)
  python bulk_crawl.py 20260401     # 특정 날짜부터 오늘까지
  python bulk_crawl.py 20260401 20260424  # 특정 기간
"""

import sys
import time
from datetime import datetime, timedelta
from database import init_db, save_game
from kbo_crawler import crawl_today_game, get_today_game_id

def date_range(start: str, end: str):
    """start ~ end 날짜 리스트 생성 (YYYYMMDD 형식)"""
    s = datetime.strptime(start, "%Y%m%d")
    e = datetime.strptime(end,   "%Y%m%d")
    while s <= e:
        yield s.strftime("%Y%m%d")
        s += timedelta(days=1)

def bulk_crawl(start_date: str, end_date: str):
    init_db()

    dates = list(date_range(start_date, end_date))
    print(f"크롤링 대상: {start_date} ~ {end_date} ({len(dates)}일)")
    print("=" * 50)

    success, skipped, failed = 0, 0, 0

    for date in dates:
        # 미래 날짜 스킵
        if date > datetime.now().strftime("%Y%m%d"):
            continue

        # 경기 있는지 먼저 확인
        game_info = get_today_game_id(date)
        if not game_info:
            print(f"  {date} — 경기 없음 (스킵)")
            skipped += 1
            time.sleep(0.5)
            continue

        # 종료된 경기만 크롤링
        if game_info.get("status") != "종료":
            print(f"  {date} — 미종료 (스킵)")
            skipped += 1
            time.sleep(0.5)
            continue

        try:
            data = crawl_today_game(date, save_json=False)
            if data:
                save_game(data)
                print(f"  {date} — 저장 완료 ✓")
                success += 1
            else:
                print(f"  {date} — 데이터 없음")
                failed += 1
        except Exception as e:
            print(f"  {date} — 오류: {e}")
            failed += 1

        time.sleep(1.5)  # 서버 부하 방지

    print("=" * 50)
    print(f"완료! 성공: {success} / 스킵: {skipped} / 실패: {failed}")

def bulk_crawl_futures(start_date: str, end_date: str):
    """퓨처스 경기 일괄 크롤링"""
    from futures_crawler import crawl_futures_game
    from database import init_db, save_futures_game

    init_db()
    dates = list(date_range(start_date, end_date))
    print(f"[퓨처스] 크롤링 대상: {start_date} ~ {end_date} ({len(dates)}일)")

    success, skipped, failed = 0, 0, 0
    for date in dates:
        if date > datetime.now().strftime("%Y%m%d"):
            continue
        try:
            data = crawl_futures_game(date, save_json=False)
            if data:
                save_futures_game(data)
                success += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"  {date} — 오류: {e}")
            failed += 1
        time.sleep(1.5)

    print(f"[퓨처스] 완료! 성공: {success} / 스킵: {skipped} / 실패: {failed}")


def recrawl_innings_only(start_date: str, end_date: str):
    """이닝 데이터만 재크롤링 (타자/투수 기록 유지)"""
    from kbo_crawler import crawl_today_game as crawl_game
    from database import init_db, get_connection

    init_db()
    conn = get_connection()

    # DB에 있는 경기만 대상으로
    games = conn.execute(
        "SELECT game_id, date FROM games WHERE date BETWEEN ? AND ? ORDER BY date",
        (start_date, end_date)
    ).fetchall()
    conn.close()

    print(f"[이닝 재크롤링] 대상: {len(games)}경기")
    success = failed = 0

    for g in games:
        game_id, date = g[0], g[1]
        try:
            data = crawl_game(date=date, save_json=False)
            if not data:
                failed += 1
                continue

            score = data.get("score_board", {})
            innings = score.get("innings", {})
            home_nm = score.get("home_team", "")
            is_home = (home_nm == "두산")

            conn2 = get_connection()
            cur = conn2.cursor()
            cur.execute("DELETE FROM inning_scores WHERE game_id=?", (game_id,))
            for team_key, team_label in [("home", "doosan" if is_home else "opponent"),
                                          ("away", "opponent" if is_home else "doosan")]:
                for i, s in enumerate(innings.get(team_key, []), start=1):
                    cur.execute(
                        "INSERT INTO inning_scores (game_id, team, inning, score) VALUES (?, ?, ?, ?)",
                        (game_id, team_label, i, s)
                    )
            conn2.commit()
            conn2.close()
            print(f"  {date} ({game_id}) — 이닝 저장 완료")
            success += 1
        except Exception as e:
            print(f"  {date} — 오류: {e}")
            failed += 1
        time.sleep(1)

    print(f"[이닝 재크롤링] 완료! 성공: {success} / 실패: {failed}")


if __name__ == "__main__":
    today = datetime.now().strftime("%Y%m%d")

    if len(sys.argv) >= 2 and sys.argv[1] == "futures":
        start = sys.argv[2] if len(sys.argv) > 2 else "20260301"
        end   = sys.argv[3] if len(sys.argv) > 3 else today
        bulk_crawl_futures(start, end)
    elif len(sys.argv) >= 2 and sys.argv[1] == "innings":
        start = sys.argv[2] if len(sys.argv) > 2 else "20240101"
        end   = sys.argv[3] if len(sys.argv) > 3 else today
        recrawl_innings_only(start, end)
    else:
        if len(sys.argv) == 3:
            start, end = sys.argv[1], sys.argv[2]
        elif len(sys.argv) == 2:
            start, end = sys.argv[1], today
        else:
            start, end = "20260301", today

        bulk_crawl(start, end)
        # 1군 완료 후 퓨처스도 크롤링
        print("\n퓨처스 크롤링 시작...")
        bulk_crawl_futures(start, end)
