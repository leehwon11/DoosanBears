"""
두산 베어스 분석 웹사이트 - 자동 스케줄러
==========================================
경기 종료 30분 후 자동으로 크롤링 → DB 저장 실행

설치:
    pip install apscheduler requests beautifulsoup4

실행:
    python scheduler.py
"""

import logging
import os
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from kbo_crawler import crawl_today_game, is_game_finished
from database import init_db, save_game
from analyzer import analyze_all

# ──────────────────────────────────────────
# 로그 설정
# ──────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),                  # 터미널 출력
        logging.FileHandler("scheduler.log"),     # 파일 저장
    ]
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────
# 핵심 작업 함수
# ──────────────────────────────────────────

def run_futures_crawl_job():
    """퓨처스 경기 자동 크롤링"""
    from futures_crawler import crawl_futures_game, is_futures_finished
    from database import save_futures_game

    now = datetime.now()
    log.info(f"[퓨처스] 작업 시작 — {now.strftime('%Y-%m-%d %H:%M')}")

    if not is_futures_finished():
        log.info("[퓨처스] 경기 미종료 또는 경기 없음 — 스킵")
        return

    data = crawl_futures_game(save_json=False)
    if not data:
        log.warning("[퓨처스] 크롤링 결과 없음")
        return

    save_futures_game(data)
    log.info("[퓨처스] DB 저장 완료")


def run_crawl_job():
    """
    경기 종료 여부 확인 후 크롤링 & DB 저장 실행.
    스케줄러가 매일 밤 10시~자정 사이 30분마다 이 함수를 호출해요.
    """
    now = datetime.now()
    log.info(f"작업 시작 — {now.strftime('%Y-%m-%d %H:%M')}")

    # 1) 오늘 두산 경기가 종료됐는지 확인
    if not is_game_finished():
        log.info("경기 미종료 또는 경기 없음 — 스킵")
        return

    log.info("경기 종료 확인 — 크롤링 시작")

    # 2) 크롤링
    data = crawl_today_game(save_json=False)  # 서버에서는 JSON 저장 불필요
    if not data:
        log.warning("크롤링 결과 없음")
        return

    # 3) DB 저장
    save_game(data)
    log.info("DB 저장 완료")

    # 4) AI 분석 실행
    game_id = data.get('game_info', {}).get('game_id')
    if game_id:
        analyze_all(game_id)


# ──────────────────────────────────────────
# 스케줄 설정
# ──────────────────────────────────────────

def start_scheduler():
    """
    스케줄러 시작.
    KBO 경기는 보통 오후 6시 30분 시작 → 9시~10시 사이 종료.
    30분 여유를 두고 밤 10시부터 자정까지 30분마다 체크해요.
    """
    init_db()  # DB 테이블 없으면 생성

    scheduler = BlockingScheduler(timezone="Asia/Seoul")

    # 매일 16:00 ~ 23:30 사이 30분마다 실행
    scheduler.add_job(
        run_crawl_job,
        trigger=CronTrigger(
            hour="16,17,18,19,20,21,22,23",
            minute="0,30",
            timezone="Asia/Seoul",
        ),
        id="kbo_crawl",
        name="KBO 두산 경기 크롤링",
        max_instances=1,        # 동시에 두 번 실행 방지
        misfire_grace_time=300, # 5분 내 지연은 그냥 실행
    )

    log.info("스케줄러 시작 — 매일 16:00~23:30 사이 30분 간격으로 실행")
    log.info("Ctrl+C 로 종료")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        log.info("스케줄러 종료")


# ──────────────────────────────────────────
# 수동 즉시 실행 (테스트용)
# ──────────────────────────────────────────

def update_players_job():
    """선수 등록 현황 자동 업데이트"""
    log.info("선수 목록 업데이트 시작")
    try:
        from player_crawler import crawl_players, save_players_to_db
        data = crawl_players()
        save_players_to_db(data)
        log.info(f"선수 목록 업데이트 완료: {len(data['roster'])}명")
    except Exception as e:
        log.error(f"선수 목록 업데이트 실패: {e}")


def run_now():
    """
    스케줄 기다리지 않고 지금 바로 크롤링.
    테스트할 때 사용: python scheduler.py now
    """
    log.info("수동 즉시 실행 모드")
    init_db()

    data = crawl_today_game(save_json=True)
    if data:
        save_game(data)
        log.info("완료")
    else:
        log.warning("데이터 없음")


# ──────────────────────────────────────────
# 실행
# ──────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "now":
        # python scheduler.py now  →  즉시 실행 (테스트용)
        run_now()
    else:
        # python scheduler.py  →  스케줄러 상시 가동
        start_scheduler()
