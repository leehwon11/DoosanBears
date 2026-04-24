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

if __name__ == "__main__":
    today = datetime.now().strftime("%Y%m%d")

    if len(sys.argv) == 3:
        start, end = sys.argv[1], sys.argv[2]
    elif len(sys.argv) == 2:
        start, end = sys.argv[1], today
    else:
        start, end = "20260301", today  # KBO 2026 시즌 개막일

    bulk_crawl(start, end)
